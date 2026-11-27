"""The sign-up policy (services/platform.py): who a first sign-in may create an
account for, in Hugging Face terms."""

import pytest

from server.services import platform


@pytest.fixture
def switches(monkeypatch):
    values: dict = {
        "signup_policy": "closed",
        "signup_orgs": [],
        "signup_usernames": [],
    }
    monkeypatch.setattr(platform, "get", lambda key: values[key])
    return values


def code(result):
    return None if result is None else result[0]


class TestCheckSignup:
    def test_closed_refuses_everybody_new(self, switches):
        assert (
            code(platform.check_signup("alice", ["open-data-lab"])) == "signup_closed"
        )

    def test_open_takes_any_account(self, switches):
        switches["signup_policy"] = "open"
        assert platform.check_signup("alice", []) is None

    def test_orgs_takes_members_of_a_listed_org(self, switches):
        switches.update(signup_policy="orgs", signup_orgs=["open-data-lab"])
        assert platform.check_signup("alice", ["Open-Data-Lab", "other"]) is None
        assert code(platform.check_signup("bob", ["other"])) == "signup_not_member"

    def test_orgs_hints_at_a_fine_grained_token_that_hides_them(self, switches):
        switches.update(signup_policy="orgs", signup_orgs=["open-data-lab"])
        refused = platform.check_signup("alice", [], fine_grained=True)
        assert code(refused) == "signup_orgs_hidden"
        assert code(platform.check_signup("alice", [])) == "signup_not_member"

    @pytest.mark.parametrize("policy", ["closed", "orgs"])
    def test_the_allow_list_bypasses_closed_and_orgs(self, switches, policy):
        switches.update(signup_policy=policy, signup_usernames=["alice"])
        assert platform.check_signup("Alice", []) is None
        assert platform.check_signup("bob", []) is not None


class TestSwitches:
    def test_unknown_policy_values_fall_back_to_closed(self, switches):
        switches["signup_policy"] = "something-old"
        assert platform.signup_policy() == "closed"

    def test_sign_up_is_possible_with_an_invitation_only(self, switches):
        assert not platform.signup_possible()
        switches["signup_usernames"] = ["alice"]
        assert platform.signup_possible()
        assert not platform.allow_signup()  # SSO still can't sign up

    def test_hf_names_are_validated_and_lowered(self):
        validate = platform.SWITCHES["signup_orgs"].validate
        assert validate(["@Open-Data-Lab", " x_y.z ", "open-data-lab"]) == [
            "open-data-lab",
            "x_y.z",
        ]
        with pytest.raises(ValueError):
            validate(["not valid!"])
        with pytest.raises(ValueError):
            validate("open-data-lab")

    def test_the_policy_is_one_of_three(self):
        validate = platform.SWITCHES["signup_policy"].validate
        assert validate("orgs") == "orgs"
        with pytest.raises(ValueError):
            validate("anyone")
