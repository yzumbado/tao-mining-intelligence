"""Unit tests for the data validation module."""



from validation import validate_metagraph, validate_registration_cost, validate_alpha_prices


class TestValidateMetagraph:
    def test_valid_metagraph_passes(self):
        data = {
            "metadata": {"source_block_number": 100},
            "data": {"neurons": [
                {"uid": 0, "emission": 0.5, "incentive": 0.6, "dividends": 0},
                {"uid": 1, "emission": 0.3, "incentive": 0.4, "dividends": 0},
                {"uid": 2, "emission": 0.1, "incentive": 0.0, "dividends": 1.0},
            ]},
        }
        is_valid, errors = validate_metagraph(data, previous_block=50)
        assert is_valid
        assert errors == []

    def test_empty_neurons_fails(self):
        data = {"metadata": {}, "data": {"neurons": []}}
        is_valid, errors = validate_metagraph(data)
        assert not is_valid
        assert "Empty metagraph" in errors[0]

    def test_block_backwards_fails(self):
        data = {
            "metadata": {"source_block_number": 30},
            "data": {"neurons": [{"uid": 0, "emission": 0, "incentive": 0, "dividends": 0}]},
        }
        is_valid, errors = validate_metagraph(data, previous_block=50)
        assert not is_valid
        assert any("backwards" in e for e in errors)

    def test_negative_emission_fails(self):
        data = {
            "metadata": {"source_block_number": 100},
            "data": {"neurons": [
                {"uid": 0, "emission": -1.0, "incentive": 0.5, "dividends": 0},
            ]},
        }
        is_valid, errors = validate_metagraph(data, previous_block=50)
        assert not is_valid
        assert any("negative emission" in e for e in errors)

    def test_incentive_sum_not_one_fails(self):
        data = {
            "metadata": {"source_block_number": 100},
            "data": {"neurons": [
                {"uid": 0, "emission": 0.5, "incentive": 0.3, "dividends": 0},
                {"uid": 1, "emission": 0.3, "incentive": 0.3, "dividends": 0},
            ]},
        }
        is_valid, errors = validate_metagraph(data, previous_block=0)
        assert not is_valid
        assert any("incentive sum" in e for e in errors)

    def test_too_many_neurons_fails(self):
        neurons = [{"uid": i, "emission": 0, "incentive": 0, "dividends": 0} for i in range(4100)]
        data = {"metadata": {}, "data": {"neurons": neurons}}
        is_valid, errors = validate_metagraph(data)
        assert not is_valid
        assert any("exceeds max 4096" in e for e in errors)

    def test_no_previous_block_skips_check(self):
        data = {
            "metadata": {"source_block_number": 10},
            "data": {"neurons": [
                {"uid": 0, "emission": 0.5, "incentive": 1.0, "dividends": 0},
            ]},
        }
        is_valid, errors = validate_metagraph(data, previous_block=0)
        assert is_valid


class TestValidateRegistrationCost:
    def test_valid_costs_pass(self):
        data = {"data": {"costs": [
            {"netuid": 1, "registration_cost_tao": 0.5},
            {"netuid": 4, "registration_cost_tao": 1.2},
        ]}}
        is_valid, errors = validate_registration_cost(data)
        assert is_valid

    def test_empty_costs_fails(self):
        data = {"data": {"costs": []}}
        is_valid, errors = validate_registration_cost(data)
        assert not is_valid

    def test_negative_cost_fails(self):
        data = {"data": {"costs": [
            {"netuid": 1, "registration_cost_tao": -0.5},
        ]}}
        is_valid, errors = validate_registration_cost(data)
        assert not is_valid


class TestValidateAlphaPrices:
    def test_valid_prices_pass(self):
        data = {"data": {"prices": [
            {"netuid": 1, "alpha_tao_price": 0.01, "pool_tao_liquidity": 28000},
        ]}}
        is_valid, errors = validate_alpha_prices(data)
        assert is_valid

    def test_negative_price_fails(self):
        data = {"data": {"prices": [
            {"netuid": 1, "alpha_tao_price": -0.01, "pool_tao_liquidity": 100},
        ]}}
        is_valid, errors = validate_alpha_prices(data)
        assert not is_valid

    def test_empty_prices_fails(self):
        data = {"data": {"prices": []}}
        is_valid, errors = validate_alpha_prices(data)
        assert not is_valid
