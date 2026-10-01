import importlib.machinery
import importlib.util
import io
import json
import pathlib
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "bin" / "herdr-snatch"
loader = importlib.machinery.SourceFileLoader("herdr_snatch", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
snatch = importlib.util.module_from_spec(spec)
loader.exec_module(snatch)


class SnatchTests(unittest.TestCase):
    def setUp(self):
        # Exercise the xdg-open path on every host; macOS would otherwise use `open`.
        platform = patch.object(snatch.sys, "platform", "linux")
        platform.start()
        self.addCleanup(platform.stop)

    def test_plugin_config_sets_default_search(self):
        with tempfile.TemporaryDirectory() as directory:
            (pathlib.Path(directory) / "settings.json").write_text('{"scope": "workspace", "source": "scrollback"}')
            with patch.dict("os.environ", {"HERDR_PLUGIN_CONFIG_DIR": directory}):
                self.assertEqual(snatch.default_search(), ("workspace", "scrollback"))

    def test_candidates_keep_recent_occurrences_and_useful_fragments(self):
        text = "old-only src/foo/parser.rs\nnew src/foo/parser.rs https://example.com/issues/123 abc123def456\n"
        values = list(snatch.candidates(text))
        self.assertEqual(values.count("src/foo/parser.rs"), 1)
        self.assertIn("https://example.com/issues/123", values)
        self.assertIn("abc123def456", values)
        self.assertIn("new src/foo/parser.rs https://example.com/issues/123 abc123def456", values)
        self.assertLess(values.index("src/foo/parser.rs"), values.index("old-only"))

    def test_candidates_join_words_wrapped_across_rows(self):
        values = list(snatch.candidates("an unusuallylongwo\nrd split across rows\n"))
        self.assertIn("unusuallylongword", values)

    @patch.dict("os.environ", {"HERDR_ACTIVE_PANE_ID": "w2:p3", "HERDR_ACTIVE_TAB_ID": "w2:t1",
                            "HERDR_ACTIVE_WORKSPACE_ID": "w2", "HERDR_BIN_PATH": "/bin/herdr"})
    @patch.object(snatch.subprocess, "run")
    def test_selection_targets_origin_without_enter(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, stdout="src/foo/parser.rs\n"),
            subprocess.CompletedProcess([], 0, stdout="\nsrc/foo/parser.rs\n"),
            subprocess.CompletedProcess([], 0, stdout=""),
        ]
        with patch.object(snatch.shutil, "which", return_value="/usr/bin/fzf"):
            snatch.main(["--scope", "pane"])
        self.assertEqual(run.call_args.args[0], ["/bin/herdr", "pane", "send-text", "w2:p3", "src/foo/parser.rs"])
        picker_args = run.call_args_list[1].args[0]
        self.assertTrue(any(arg.startswith("--bind=ctrl-w:transform(") for arg in picker_args))

    @patch.dict("os.environ", {"HERDR_ACTIVE_PANE_ID": "w2:p3", "HERDR_ACTIVE_TAB_ID": "w2:t1",
                            "HERDR_ACTIVE_WORKSPACE_ID": "w2"})
    @patch.object(snatch.subprocess, "run")
    def test_cancel_does_not_send_text(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, stdout="src/foo/parser.rs\n"),
            subprocess.CompletedProcess([], 130, stdout=""),
        ]
        with patch.object(snatch.shutil, "which", return_value="/usr/bin/fzf"):
            snatch.main(["--scope", "pane"])
        self.assertEqual(run.call_count, 2)

    def test_missing_fzf_explains_how_to_close_popup(self):
        environment = {"HERDR_ACTIVE_PANE_ID": "w2:p3", "HERDR_ACTIVE_TAB_ID": "w2:t1",
                       "HERDR_ACTIVE_WORKSPACE_ID": "w2"}
        with patch.dict("os.environ", environment), patch.object(snatch.shutil, "which", return_value=None), \
             patch.object(snatch.subprocess, "run") as run, patch("sys.stdin", io.StringIO("\n")), \
             redirect_stdout(io.StringIO()) as output:
            snatch.main(["--scope", "pane"])
        self.assertIn("fzf is required", output.getvalue())
        self.assertIn("press Enter to close", output.getvalue())
        run.assert_not_called()

    def test_copy_uses_clipboard_without_sending_to_pane(self):
        environment = {"HERDR_ACTIVE_PANE_ID": "w2:p3", "HERDR_ACTIVE_TAB_ID": "w2:t1",
                       "HERDR_ACTIVE_WORKSPACE_ID": "w2", "WAYLAND_DISPLAY": "wayland-1"}
        with patch.dict("os.environ", environment), patch.object(snatch.shutil, "which", return_value="/usr/bin/wl-copy"), \
             patch.object(snatch.subprocess, "run") as run:
            run.side_effect = [
                subprocess.CompletedProcess([], 0, stdout="path with spaces.txt\n"),
                subprocess.CompletedProcess([], 0, stdout="ctrl-y\npath with spaces.txt\n"),
                subprocess.CompletedProcess([], 0, stdout=""),
            ]
            snatch.main(["--scope", "pane"])
        self.assertEqual(run.call_args.args[0], ["wl-copy"])
        self.assertEqual(run.call_args.kwargs["input"], "path with spaces.txt")

    def test_open_resolves_path_from_originating_pane(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "parser rules.rs"
            path.touch()
            environment = {"HERDR_ACTIVE_PANE_ID": "w2:p3", "HERDR_ACTIVE_TAB_ID": "w2:t1",
                           "HERDR_ACTIVE_WORKSPACE_ID": "w2", "HERDR_ACTIVE_PANE_CWD": directory}
            with patch.dict("os.environ", environment), patch.object(snatch.shutil, "which", return_value="/usr/bin/xdg-open"), \
                 patch.object(snatch.subprocess, "run") as run, patch.object(snatch.subprocess, "Popen") as popen:
                run.side_effect = [
                    subprocess.CompletedProcess([], 0, stdout="parser rules.rs\n"),
                    subprocess.CompletedProcess([], 0, stdout="ctrl-o\nparser rules.rs\n"),
                ]
                snatch.main(["--scope", "pane"])
            self.assertEqual(run.call_count, 2)
            self.assertEqual(popen.call_args.args[0], ["xdg-open", str(path.resolve())])
            self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_plugin_open_resolves_path_from_originating_pane(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "parser rules.rs"
            path.touch()
            pane = {"result": {"pane": {"foreground_cwd": directory, "cwd": "/wrong"}}}
            with patch.dict("os.environ", {"HERDR_ACTIVE_PANE_CWD": ""}), \
                 patch.object(snatch.shutil, "which", return_value="/usr/bin/xdg-open"), \
                 patch.object(snatch.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout=json.dumps(pane))) as run, \
                 patch.object(snatch.subprocess, "Popen") as popen:
                snatch.open_target(path.name, "w2:p3", "/bin/herdr")
            run.assert_called_once_with(["/bin/herdr", "pane", "get", "w2:p3"], check=True, capture_output=True, text=True)
            self.assertEqual(popen.call_args.args[0], ["xdg-open", str(path.resolve())])

    def test_open_url_as_one_argument(self):
        url = "https://example.com/issues/123?a=1&b=2"
        with patch.object(snatch.shutil, "which", return_value="/usr/bin/xdg-open"), \
             patch.object(snatch.subprocess, "Popen") as popen:
            snatch.open_target(url)
        self.assertEqual(popen.call_args.args[0], ["xdg-open", url])

    @patch.object(snatch.subprocess, "run")
    def test_scope_and_source_choose_panes_and_read_mode(self, run):
        panes = [
            {"pane_id": "w2:p3", "tab_id": "w2:t1"},
            {"pane_id": "w2:p4", "tab_id": "w2:t1"},
            {"pane_id": "w2:p5", "tab_id": "w2:t2"},
        ]
        reads = []

        def fake_run(command, **kwargs):
            if command[1:3] == ["pane", "list"]:
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"result": {"panes": panes}}))
            reads.append(command)
            return subprocess.CompletedProcess(command, 0, stdout=command[3] + "\n")

        run.side_effect = fake_run
        tab = list(snatch.choices("herdr", "w2:p3", "w2:t1", "w2", "tab", "visible"))
        self.assertEqual(tab, ["w2:p3", "w2:p4"])
        self.assertTrue(all(command[4:] == ["--source", "visible"] for command in reads))

        reads.clear()
        workspace = list(snatch.choices("herdr", "w2:p3", "w2:t1", "w2", "workspace", "scrollback"))
        self.assertEqual(workspace, ["w2:p3", "w2:p4", "w2:p5"])
        self.assertTrue(all(command[4:] == ["--source", "recent-unwrapped", "--lines", "10000000"] for command in reads))

    @patch.dict("os.environ", {"HERDR_ACTIVE_PANE_ID": "w2:p3", "HERDR_ACTIVE_TAB_ID": "w2:t1",
                            "HERDR_ACTIVE_WORKSPACE_ID": "w2"})
    @patch.object(snatch.subprocess, "run")
    def test_switch_keeps_scope_when_source_changes(self, run):
        def fake_run(command, **kwargs):
            if command[1:3] == ["pane", "list"]:
                output = json.dumps({"result": {"panes": [{"pane_id": "w2:p3", "tab_id": "w2:t1"}]}})
            else:
                output = "src/foo/parser.rs\n"
            return subprocess.CompletedProcess(command, 0, stdout=output)

        run.side_effect = fake_run
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory) / "mode"
            state.write_text("tab scrollback")
            with redirect_stdout(io.StringIO()) as output:
                snatch.main(["--switch", str(state), "source", "visible"])
            self.assertEqual(state.read_text(), "tab visible")
            self.assertIn("reload(", output.getvalue())
            with redirect_stdout(io.StringIO()) as listing:
                snatch.main(["--list", str(state)])
            self.assertIn("tab/visible", listing.getvalue())
            self.assertIn("src/foo/parser.rs", listing.getvalue())


OPENERS = [
    {"name": "PR", "match": r"(?:PR #?|(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)#)(?P<number>\d+)", "priority": 100,
     "defaults": {"owner": "acme", "repo": "app"},
     "url": "https://code.example/repos/{owner}/{repo}/pulls/{number}"},
    {"name": "Ticket", "match": r"(?:ticket[- ]|TK )(?P<number>\d+)", "priority": 100,
     "url": "https://tickets.example/{number}"},
    {"name": "Bare PR", "match": r"#?(?P<number>\d+)", "url": "https://code.example/pulls/{number}"},
    {"name": "Bare ticket", "match": r"#?(?P<number>\d+)", "command": ["open-ticket", "{number}"]},
]


class OpenerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        (pathlib.Path(self.directory.name) / "settings.json").write_text(json.dumps({"openers": OPENERS}))
        environment = patch.dict("os.environ", {"HERDR_PLUGIN_CONFIG_DIR": self.directory.name})
        environment.start()
        self.addCleanup(environment.stop)
        self.openers = snatch.load_openers()

    def test_prefixed_numbers_become_candidates_only_when_an_opener_matches(self):
        values = list(snatch.candidates("see PR #4321 and TK 1628, timeout 120\n", self.openers))
        self.assertIn("PR #4321", values)
        self.assertIn("TK 1628", values)
        self.assertNotIn("timeout 120", values)
        self.assertIn("120", values)

    def test_owner_repo_reference_fills_fields_and_defaults(self):
        (opener, fields), = [m for m in snatch.matching_openers("octo/widgets#54557", self.openers)
                            if m[0]["name"] == "PR"]
        self.assertEqual(snatch.opener_target(opener, fields), "https://code.example/repos/octo/widgets/pulls/54557")
        (opener, fields), = snatch.matching_openers("PR 7", self.openers)
        self.assertEqual(snatch.opener_target(opener, fields), "https://code.example/repos/acme/app/pulls/7")

    def test_highest_priority_opener_opens_without_asking(self):
        with patch.object(snatch.subprocess, "run") as run, patch.object(snatch.subprocess, "Popen") as popen, \
             patch.object(snatch.shutil, "which", return_value="/usr/bin/xdg-open"), \
             patch.object(snatch.sys, "platform", "linux"):
            snatch.open_selection("ticket-1628", "w2:p3", "herdr")
        run.assert_not_called()
        self.assertEqual(popen.call_args.args[0], ["xdg-open", "https://tickets.example/1628"])

    def test_tied_openers_ask_and_run_the_chosen_command(self):
        with patch.object(snatch.subprocess, "run") as run, patch.object(snatch.subprocess, "Popen") as popen:
            run.return_value = subprocess.CompletedProcess([], 0, stdout="1\tBare ticket\topen-ticket 1628\n")
            snatch.open_selection("#1628", "w2:p3", "herdr")
        self.assertIn("0\tBare PR\thttps://code.example/pulls/1628", run.call_args.kwargs["input"])
        self.assertEqual(popen.call_args.args[0], ["open-ticket", "1628"])

    def test_cancelling_the_chooser_opens_nothing(self):
        with patch.object(snatch.subprocess, "run") as run, patch.object(snatch.subprocess, "Popen") as popen:
            run.return_value = subprocess.CompletedProcess([], 130, stdout="")
            snatch.open_selection("1628", "w2:p3", "herdr")
        popen.assert_not_called()

    def test_unmatched_selection_falls_back_to_url_and_path_opening(self):
        with patch.object(snatch, "open_target") as open_target:
            snatch.open_selection("https://example.com/x", "w2:p3", "herdr")
        open_target.assert_called_once_with("https://example.com/x", "w2:p3", "herdr")

    def test_settings_override_builtin_opener_by_name(self):
        settings = {"openers": [{"name": "GitHub", "match": "(?!)", "url": "x"}]}
        (pathlib.Path(self.directory.name) / "settings.json").write_text(json.dumps(settings))
        self.assertEqual(snatch.matching_openers("a/b#1", snatch.load_openers()), [])


if __name__ == "__main__":
    unittest.main()
