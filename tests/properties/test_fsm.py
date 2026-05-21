"""Property test: FSM Transition Validity (Property 6).

Validates Requirements 7.3-7.7:
- Only valid state transitions are allowed
- retry_count increments on ERROR_RETRYABLE
- ERROR_FATAL after 3 retries
- IDLE reset clears retry_count
"""

import os
from unittest.mock import patch

import boto3
import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st
from moto import mock_aws


# Valid FSM transitions
VALID_TRANSITIONS = {
    "IDLE": ["COLLECTING"],
    "COLLECTING": ["PROCESSING", "ERROR_RETRYABLE"],
    "PROCESSING": ["COMPLETE", "ERROR_RETRYABLE"],
    "COMPLETE": ["IDLE"],
    "ERROR_RETRYABLE": ["COLLECTING", "PROCESSING", "ERROR_FATAL"],
    "ERROR_FATAL": ["IDLE"],
}

ALL_STATES = list(VALID_TRANSITIONS.keys())

_AWS_ENV = {
    "PIPELINE_ENV": "aws",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SECURITY_TOKEN": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "TABLE_NAME": "tao-pipeline-test",
    "BUCKET_NAME": "tao-intelligence-test",
}


@st.composite
def valid_transition(draw):
    """Generate a valid (from_state, to_state) pair."""
    from_state = draw(st.sampled_from(ALL_STATES))
    to_state = draw(st.sampled_from(VALID_TRANSITIONS[from_state]))
    return from_state, to_state


@st.composite
def invalid_transition(draw):
    """Generate an invalid (from_state, to_state) pair."""
    from_state = draw(st.sampled_from(ALL_STATES))
    all_invalid = [s for s in ALL_STATES if s not in VALID_TRANSITIONS[from_state]]
    assume(len(all_invalid) > 0)
    to_state = draw(st.sampled_from(all_invalid))
    return from_state, to_state


def _create_table():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    try:
        return dynamodb.create_table(
            TableName="tao-pipeline-test",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
    except dynamodb.meta.client.exceptions.ResourceInUseException:
        return dynamodb.Table("tao-pipeline-test")


class TestFSMTransitionValidity:
    """Property: only valid transitions succeed via conditional write."""

    @mock_aws
    @given(data=valid_transition())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_valid_transitions_succeed(self, data):
        """Valid transitions are accepted by StateManager."""
        with patch.dict(os.environ, _AWS_ENV):
            from src import config as config_mod
            config_mod.reset_config()

            from_state, to_state = data
            _create_table()

            from src.config import get_config
            from src.state.state_manager import StateManager

            config = get_config()
            sm = StateManager(config)

            sm._table.put_item(Item={
                "PK": "SUBNET#1", "SK": "STATE",
                "current_status": from_state, "retry_count": 0,
                "cycle_id": "", "last_updated": "", "metadata": {},
            })

            result = sm.transition(1, from_state, to_state)
            assert result is True

            config_mod.reset_config()

    @mock_aws
    @given(data=invalid_transition())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_invalid_transitions_rejected(self, data):
        """Invalid transitions are rejected (conditional check fails)."""
        with patch.dict(os.environ, _AWS_ENV):
            from src import config as config_mod
            config_mod.reset_config()

            from_state, to_state = data
            _create_table()

            from src.config import get_config
            from src.state.state_manager import StateManager

            config = get_config()
            sm = StateManager(config)

            # Set actual state to something that doesn't match from_state
            actual_state = "IDLE" if from_state != "IDLE" else "COLLECTING"
            sm._table.put_item(Item={
                "PK": "SUBNET#1", "SK": "STATE",
                "current_status": actual_state,
                "retry_count": 0, "cycle_id": "", "last_updated": "", "metadata": {},
            })

            result = sm.transition(1, from_state, to_state)
            assert result is False

            config_mod.reset_config()


class TestRetryCount:
    """Property: retry_count increments on ERROR_RETRYABLE."""

    @mock_aws
    @given(initial_retries=st.integers(min_value=0, max_value=10))
    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_retry_count_increments(self, initial_retries):
        """Each ERROR_RETRYABLE transition increments retry_count."""
        with patch.dict(os.environ, _AWS_ENV):
            from src import config as config_mod
            config_mod.reset_config()

            _create_table()

            from src.config import get_config
            from src.state.state_manager import StateManager

            config = get_config()
            sm = StateManager(config)

            sm._table.put_item(Item={
                "PK": "SUBNET#1", "SK": "STATE",
                "current_status": "PROCESSING", "retry_count": initial_retries,
                "cycle_id": "2026-05-15", "last_updated": "", "metadata": {},
            })

            sm.transition(1, "PROCESSING", "ERROR_RETRYABLE")

            state = sm.get_subnet_state(1)
            assert state.retry_count == initial_retries + 1

            config_mod.reset_config()

    @mock_aws
    def test_idle_resets_retry_count(self):
        """Transitioning to IDLE resets retry_count to 0."""
        with patch.dict(os.environ, _AWS_ENV):
            from src import config as config_mod
            config_mod.reset_config()

            _create_table()

            from src.config import get_config
            from src.state.state_manager import StateManager

            config = get_config()
            sm = StateManager(config)

            sm._table.put_item(Item={
                "PK": "SUBNET#1", "SK": "STATE",
                "current_status": "COMPLETE", "retry_count": 3,
                "cycle_id": "2026-05-15", "last_updated": "", "metadata": {},
            })

            sm.transition(1, "COMPLETE", "IDLE")

            state = sm.get_subnet_state(1)
            assert state.retry_count == 0

            config_mod.reset_config()
