from server.core.i18n import catalog, pick_locale, tr
from server.jobs.registry import JOBS
from server.services import platform


def test_the_readers_pick_then_their_browser_then_english():
    assert pick_locale("fr", "en-US") == "fr"
    assert pick_locale(None, "de;q=0.9,fr;q=0.5") == "fr"
    assert pick_locale("de", "es") == "en"


def test_french_falls_back_to_english_and_fills_values():
    assert tr("fr", "no.such.key", "Hello {name}", name="Ada") == "Hello Ada"
    assert tr("en", "platform.allow_signup", "English") == "English"


def test_every_listed_job_and_switch_has_french():
    french = catalog("fr")
    for spec in JOBS.values():
        if spec.listed:
            assert f"jobs.{spec.id}.title" in french
            assert f"jobs.{spec.id}.description" in french
            for label, _ in spec.requires:
                assert f"missing.{label}" in french
    for key in platform.SWITCHES:
        assert f"platform.{key}" in french


def test_a_runs_metrics_are_shown_in_the_readers_language():
    from server.core.i18n import metrics_display

    stored = [
        ["Pairs", 46],
        ["Embedding model", "none"],
        [
            "Embedding checks",
            "3 new pair(s) checked for rephrasings and grounding, "
            "1 changed pair(s) re-checked against their source",
        ],
        ["Something new", "an unknown sentence"],
    ]
    assert metrics_display(stored, "en") == stored
    shown = metrics_display(stored, "fr")
    assert shown[0] == ["Paires", 46]
    assert shown[1] == ["Modèle d'embedding", "aucun"]
    assert (
        shown[2][1].startswith("3 nouvelle(s) paire(s)")
        and "1 paire(s) modifiée(s)" in shown[2][1]
    )
    assert shown[3] == ["Something new", "an unknown sentence"]


def test_the_api_serves_a_run_in_the_language_of_the_cookie(
    client, owner, test_db, datasets_db, monkeypatch
):
    from server.models.job_run import JobRun

    # Runs are read through a session of their own: the same test database.
    monkeypatch.setattr("server.services.jobs.get_scoped_db", datasets_db)

    test_db.add(
        JobRun(
            id="run-fr",
            job_id="github-personal",
            owner_id=owner.id,
            status="succeeded",
            options={},
            result={"dry_run": False, "metrics": [["Kept", 39]], "errors": []},
        )
    )
    test_db.commit()

    english = client.get("/jobs/runs/run-fr").json()["result"]
    client.cookies.set("dg-locale", "fr")
    french = client.get("/jobs/runs/run-fr").json()["result"]

    assert english["metrics"] == french["metrics"] == [["Kept", 39]]
    assert english["metrics_display"] == [["Kept", 39]]
    assert french["metrics_display"] == [["Conservées", 39]]


def test_the_servers_own_messages_are_shown_in_the_readers_language():
    from server.core.i18n import translate_message as _translate

    def translate_message(text, locale):
        # French typography: non-breaking spaces before ":" and inside « ».
        shown = _translate(text, locale)
        return shown.replace("\u00a0", " ") if shown else shown

    unknown_model = "Unknown model 'openai:x'. Available: openai:a, openai:b"
    assert translate_message(unknown_model, "en") == unknown_model
    assert translate_message(unknown_model, "fr") == (
        "Modèle inconnu « openai:x ». Disponibles : openai:a, openai:b"
    )
    assert translate_message("Daily limit reached (20 runs in 24 h).", "fr") == (
        "Limite quotidienne atteinte (20 exécutions en 24 h)."
    )
    # A label the message names is translated too.
    assert (
        translate_message(
            "your API key (and endpoint) is required to run openai:x", "fr"
        )
        == "votre clé d'API (et son endpoint) est requis pour lancer openai:x"
    )


def test_a_message_the_server_does_not_know_stays_as_stored():
    from server.core.i18n import translate_message

    upstream = "401 Client Error: Unauthorized for url: https://huggingface.co/api"
    assert translate_message(upstream, "fr") == upstream
    assert translate_message(None, "fr") is None


def test_the_api_serves_a_failed_runs_error_in_the_language_of_the_cookie(
    client, owner, test_db, datasets_db, monkeypatch
):
    from server.models.job_run import JobRun

    monkeypatch.setattr("server.services.jobs.get_scoped_db", datasets_db)
    test_db.add(
        JobRun(
            id="run-failed",
            job_id="github-personal",
            owner_id=owner.id,
            status="failed",
            options={},
            error="Your Hugging Face token is required (add it in Settings)",
        )
    )
    test_db.commit()

    english = client.get("/jobs/runs/run-failed").json()["error"]
    client.cookies.set("dg-locale", "fr")
    french = client.get("/jobs/runs/run-failed").json()["error"]

    assert english == "Your Hugging Face token is required (add it in Settings)"
    assert (
        french == "Votre jeton Hugging Face est requis (ajoutez-le dans les Paramètres)"
    )


def test_each_french_message_keeps_the_placeholders_of_its_english():
    import json
    from pathlib import Path
    from string import Formatter

    from server.core import i18n

    def names(text):
        return sorted(name for _, name, _, _ in Formatter().parse(text) if name)

    french = json.loads(
        (Path(i18n.__file__).parent / "locales" / "fr.json").read_text()
    )
    for english, translated in french["messages"].items():
        assert names(translated) == names(english), english


def test_an_api_error_is_sent_in_the_language_of_the_cookie(
    client, datasets_db, monkeypatch
):
    monkeypatch.setattr("server.services.jobs.get_scoped_db", datasets_db)

    english = client.get("/jobs/runs/no-such-run")
    client.cookies.set("dg-locale", "fr")
    french = client.get("/jobs/runs/no-such-run")

    assert english.status_code == french.status_code == 404
    assert english.json()["detail"] == "Unknown run 'no-such-run'"
    assert (
        french.json()["detail"].replace("\u00a0", " ")
        == "Exécution inconnue « no-such-run »"
    )


def test_an_operation_named_in_an_error_is_translated_too():
    from server.core.i18n import translate_message

    failed = "Deleting the dataset failed. Try again; if it keeps failing, the server logs say why."
    shown = str(translate_message(failed, "fr")).replace("\u00a0", " ")
    assert shown.startswith("La suppression du jeu de données a échoué.")
    named = str(
        translate_message("Reading the history of kevindb/x failed", "fr")
    ).replace("\u00a0", " ")
    assert named == "Échec de la lecture : l'historique de kevindb/x"
