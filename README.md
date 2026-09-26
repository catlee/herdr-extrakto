<h1 align=center><code>herdr-snatch</code></h1>

<div align=center>
<a href="https://github.com/catlee/herdr-snatch/actions/workflows/ci.yml"><img src="https://github.com/catlee/herdr-snatch/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
</div>

`herdr-snatch` is a fuzzy picker for text already on your Herdr screen. Search it with `fzf`, then insert, copy, or open the result.

> The path is right there. Why am I typing it again?

## Why herdr-snatch?

Mouse selection across split panes works, but I kept grabbing one slash too many. [tmux-extrakto](https://github.com/laktak/extrakto) gave me the idea: put an `fzf` picker over Herdr and send the selection back to the pane that opened it.

## Install

You need Herdr 0.8.2 or newer, Python 3.9 or newer, and `fzf`.

```sh
herdr plugin install catlee/herdr-snatch
```

Add this to `~/.config/herdr/config.toml`:

```toml
[keys]
cycle_pane_next = "prefix+alt+o" # free up prefix+Tab

[[keys.command]]
key = "prefix+tab"
type = "plugin_action"
command = "herdr-snatch.open"
description = "Pick text from pane output"
```

If you already have a `[keys]` section, add `cycle_pane_next` there instead of creating another one. Then run `herdr server reload-config`.

## Quick start

Say the build has just printed a file path:

```text
$ cargo build
error: src/parser/rules.rs
$ vim █

prefix+Tab  →  type pars  →  Enter

$ vim src/parser/rules.rs█
```

## Keys

| Key | What it does |
| --- | --- |
| `prefix+Tab` | Open the picker |
| Type, `↑`, `↓` | Search and move through matches |
| `Enter` or `Tab` | Insert in the pane that opened the picker, without running the command |
| `Ctrl-Y` | Copy to the system clipboard |
| `Ctrl-O` | Open a URL or local path in its default app |
| `Esc` | Cancel |
| `Ctrl-P`, `Ctrl-T`, `Ctrl-W` | Search one pane, the current tab, or the workspace |
| `Ctrl-V`, `Ctrl-R` | Search visible screens or retained scrollback |

The popup shows the current search scope. Switching scope keeps your query. It starts at **tab/visible**. To change that default, put a `settings.json` file in the directory printed by `herdr plugin config-dir herdr-snatch`:

```json
{"scope": "pane", "source": "scrollback"}
```

Valid scopes are `pane`, `tab`, and `workspace`; sources are `visible` and `scrollback`. Omit either setting to keep its default.

## Search scope and candidates

The picker pulls text from Herdr with `pane read`, then extracts paths, URLs, hex hashes, words, and whole non-empty lines. Duplicates are removed, with the originating pane searched first. `fzf` ranks matches against what you type. Scrollback reads up to 10 million rendered rows per pane, bounded by what Herdr retains. Large histories can take longer; lower `SCROLLBACK_LINES` in the script if that becomes annoying.

Insert sends the selected text literally to the original pane. It doesn't press Enter or add shell quotes. Copy passes the exact text to `wl-copy` (Wayland), `xclip` (X11), or `pbcopy` (macOS). Open uses `xdg-open` (Linux) or `open` (macOS); relative paths are resolved from the original pane's working directory and must exist. These commands run on the machine hosting the Herdr popup, which matters if you're using a remote session.

## Development

Link a local checkout instead of installing from GitHub:

```sh
herdr plugin link .
```

Herdr reads scripts from the linked checkout. After changing `herdr-plugin.toml`, unlink and link it again. Herdr won't install a GitHub copy over a local link; run `herdr plugin unlink herdr-snatch` first when switching back. There are no Python packages to install. Run the tests with:

```sh
python3 -m unittest discover -s tests -v
```

CI runs the same tests on Python 3.9 and 3.14. The code is under the [MIT license](LICENSE).
