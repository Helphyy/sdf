"""Tests headless de la logique clé de sdf via le pilote Textual."""

import asyncio
import os
import tempfile
from pathlib import Path

# Isole la config persistante dans un dossier jetable (ne pas polluer ~/.config).
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="sdf_cfg_")

from sdf.app import SdfApp, ConflictScreen


async def _run_all() -> None:
    tmpdir = Path(tempfile.mkdtemp(prefix="sdf_test_"))
    target = tmpdir / "doc.md"
    target.write_text("# Hello\n", encoding="utf-8")

    # --- Cas 1 & 2 : chargement + reload auto sur modif externe (buffer propre)
    app = SdfApp(path=str(target), conflict_mode="auto")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.editor.text == "# Hello\n", "chargement initial KO"
        assert not app._dirty, "buffer neuf doit être propre"

        # modif externe, buffer propre -> adoption silencieuse
        target.write_text("# Externe\n", encoding="utf-8")
        app._last_disk_mtime = None  # force la détection
        app._check_file()
        await pilot.pause()
        assert app.editor.text == "# Externe\n", "reload auto (buffer propre) KO"
        assert not app._dirty, "après reload le buffer doit être propre"

        # --- Cas 3 : modif externe avec buffer sale -> modale conflit, choix K
        app.editor.load_text("# Externe\nmes notes locales\n")  # rend sale
        await pilot.pause()
        assert app._dirty, "le buffer aurait dû devenir sale"
        target.write_text("# Autre version disque\n", encoding="utf-8")
        app._last_disk_mtime = None
        app._check_file()
        await pilot.pause()
        assert isinstance(app.screen, ConflictScreen), "modale de conflit non ouverte"
        await pilot.press("k")  # garder mon buffer
        await pilot.pause()
        assert app.editor.text == "# Externe\nmes notes locales\n", "buffer local non conservé"
        assert app._ignored_disk_text == "# Autre version disque\n", "version disque non ignorée"

        # ré-appel : la même version disque ignorée ne redéclenche pas de modale
        app._last_disk_mtime = None
        app._check_file()
        await pilot.pause()
        assert not isinstance(app.screen, ConflictScreen), "modale rouverte sur version ignorée"

        # --- Cas 4 : sauvegarde ne déclenche pas de fausse alerte externe
        app.editor.load_text("# Sauvé par moi\n")
        await pilot.pause()
        app.action_save()
        await pilot.pause()
        assert target.read_text(encoding="utf-8") == "# Sauvé par moi\n", "sauvegarde KO"
        assert not app._dirty, "après save le buffer doit être propre"
        app._check_file()  # mtime à jour -> aucune alerte
        await pilot.pause()
        assert not isinstance(app.screen, ConflictScreen), "fausse alerte après notre propre save"

    # --- Cas 5 : fichier inexistant créé à la sauvegarde, sans dossier parasite
    newfile = tmpdir / "sub" / "created.md"
    app2 = SdfApp(path=str(newfile), conflict_mode="auto")
    async with app2.run_test() as pilot:
        await pilot.pause()
        assert app2.editor.text == "", "un fichier inexistant doit ouvrir un buffer vide"
        app2.editor.load_text("contenu neuf\n")
        await pilot.pause()
        app2.action_save()
        await pilot.pause()
        assert newfile.exists(), "le fichier n'a pas été créé à la sauvegarde"
        assert newfile.read_text(encoding="utf-8") == "contenu neuf\n"

    print("OK - cas nominaux passent")
    await _regressions(tmpdir)
    print("OK - régressions passent")
    await _features(tmpdir)
    print("OK - tous les cas (nominaux + régressions + features) passent")


async def _regressions(tmpdir) -> None:
    """Régressions pour chaque bug confirmé par le workflow de durcissement."""
    from sdf.app import UnsavedScreen

    # --- Rég. A : contenu non-UTF8 ne crashe ni au démarrage ni au poll (issue: read-disk-unicode-crash)
    latin = tmpdir / "latin.md"
    latin.write_bytes(b"# R\xe9sum\xe9\n")  # latin-1, invalide en UTF-8
    appA = SdfApp(path=str(latin), conflict_mode="auto")
    async with appA.run_test() as pilot:  # ne doit pas lever au montage
        await pilot.pause()
        assert appA.editor.text != "", "un fichier non-UTF8 ne doit pas ouvrir un buffer vide"
        assert appA.return_code is None, "l'app a crashé au démarrage sur non-UTF8"
        # écriture externe non-UTF8 pendant la surveillance -> pas de crash du timer
        latin.write_bytes(b"# caf\xe9 garbage \xff\xfe\n")
        appA._last_disk_sig = None
        appA._check_file()  # ne doit pas lever
        await pilot.pause()
        assert appA.return_code is None, "le poll a crashé sur écriture externe non-UTF8"

    # --- Rég. B : Ctrl+W cycle le ratio sans muter le buffer (issue: ctrl-w-deletes-word)
    docB = tmpdir / "b.md"
    docB.write_text("hello world foo bar\n", encoding="utf-8")
    appB = SdfApp(path=str(docB), conflict_mode="auto")
    async with appB.run_test() as pilot:
        await pilot.pause()
        appB.editor.focus()
        await pilot.pause()
        idx0, text0 = appB._ratio_idx, appB.editor.text
        await pilot.press("ctrl+w")
        await pilot.pause()
        assert appB._ratio_idx != idx0, "Ctrl+W n'a pas cyclé le ratio (avalé par TextArea)"
        assert appB.editor.text == text0, "Ctrl+W a muté le buffer (delete_word_left)"
        # Ctrl+E doit basculer l'explorateur, pas déplacer le curseur
        vis0 = appB.sidebar.display
        await pilot.press("ctrl+e")
        await pilot.pause()
        assert appB.sidebar.display != vis0, "Ctrl+E n'a pas basculé l'explorateur"

    # --- Rég. C : modif externe à mtime identique mais taille différente est détectée (issue: mtime-equal)
    import os
    docC = tmpdir / "c.md"
    docC.write_text("# version A\n", encoding="utf-8")
    st = docC.stat()
    appC = SdfApp(path=str(docC), conflict_mode="auto")
    async with appC.run_test() as pilot:
        await pilot.pause()
        docC.write_text("# version B beaucoup plus longue\n", encoding="utf-8")
        os.utime(docC, ns=(st.st_mtime_ns, st.st_mtime_ns))  # restaure le mtime d'origine
        appC._check_file()
        await pilot.pause()
        assert "version B" in appC.editor.text, "modif externe à mtime identique non détectée"

    # --- Rég. D : version ignorée non re-proposée sur buffer propre en mode prompt (issue: ignored-version)
    docD = tmpdir / "d.md"
    docD.write_text("# Original\n", encoding="utf-8")
    appD = SdfApp(path=str(docD), conflict_mode="prompt")
    async with appD.run_test() as pilot:
        await pilot.pause()
        docD.write_text("# V1 externe\n", encoding="utf-8")
        appD._last_disk_sig = None
        appD._check_file()
        await pilot.pause()
        assert isinstance(appD.screen, ConflictScreen), "1er prompt attendu"
        await pilot.press("k")  # garder mon buffer -> ignore V1
        await pilot.pause()
        assert appD._ignored_disk_text == "# V1 externe\n"
        os.utime(docD, None)  # re-touche mtime, même contenu V1
        appD._last_disk_sig = None
        appD._check_file()
        await pilot.pause()
        assert not isinstance(appD.screen, ConflictScreen), "version ignorée re-proposée (buffer propre)"

    # --- Rég. E : échec de sauvegarde ne jette pas le buffer non sauvé (issue: save-open-dataloss)
    work = tmpdir / "work.md"
    other = tmpdir / "other.md"
    work.write_text("# work\n", encoding="utf-8")
    other.write_text("# other\n", encoding="utf-8")
    appE = SdfApp(path=str(work), conflict_mode="auto")
    async with appE.run_test() as pilot:
        await pilot.pause()
        appE.editor.load_text("PRECIEUX travail non sauvé\n")
        await pilot.pause()
        os.remove(work)
        os.mkdir(work)  # write_text -> IsADirectoryError (OSError) => save échoue
        appE._open_path(other)
        await pilot.pause()
        assert isinstance(appE.screen, UnsavedScreen)
        await pilot.press("s")  # Sauver + ouvrir, mais le save va échouer
        await pilot.pause()
        await pilot.pause()
        assert appE.editor.text == "PRECIEUX travail non sauvé\n", "buffer perdu malgré échec de save"
        assert appE._path == work.resolve(), "on a basculé de fichier alors que le save a échoué"

    # --- Rég. F : changer de fichier via l'explorateur (bug _ui_ready jamais True)
    fdir = tmpdir / "browse"
    fdir.mkdir()
    (fdir / "a.md").write_text("# AAA\n", encoding="utf-8")
    (fdir / "b.md").write_text("# BBB\n", encoding="utf-8")
    appF = SdfApp(path=str(fdir / "a.md"))
    async with appF.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        assert appF._ui_ready is True, "_ui_ready doit être True après le montage"
        await pilot.press("ctrl+e")
        await pilot.pause()
        appF.filetree.focus()
        await pilot.pause()
        for _ in range(6):
            cn = appF.filetree.cursor_node
            if cn and "b.md" in str(cn.label):
                break
            await pilot.press("down")
            await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert appF._path.name == "b.md", "changement de fichier via l'arbre KO"
        assert "BBB" in appF.editor.text


async def _features(tmpdir) -> None:
    """Nouvelles fonctionnalités: modes de vue, transparence, thème, persistance."""
    # Config vierge, isolée de la persistance des tests précédents.
    os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="sdf_feat_")
    doc = tmpdir / "feat.md"
    doc.write_text("# hi\n", encoding="utf-8")

    # --- Thème par défaut = gruvbox (config vierge) + modes de vue plein écran
    appV = SdfApp(path=str(doc))
    async with appV.run_test() as pilot:
        await pilot.pause()
        assert appV.theme == "gruvbox", f"thème par défaut attendu gruvbox, obtenu {appV.theme}"
        # split -> editor plein -> preview plein -> split
        assert appV._view_mode == "split"
        assert appV.editor.display and appV.preview_scroll.display
        await pilot.press("ctrl+f")
        await pilot.pause()
        assert appV._view_mode == "editor" and appV.editor.display and not appV.preview_scroll.display
        await pilot.press("ctrl+f")
        await pilot.pause()
        assert appV._view_mode == "preview" and appV.preview_scroll.display and not appV.editor.display
        await pilot.press("ctrl+f")
        await pilot.pause()
        assert appV._view_mode == "split" and appV.editor.display and appV.preview_scroll.display

    # --- Transparence: toggle on/off (via commande palette / action)
    appT = SdfApp(path=str(doc))
    async with appT.run_test() as pilot:
        await pilot.pause()
        assert appT._transparent is False and not appT.editor.has_class("transparent")
        appT.action_toggle_transparency()  # on (commande de la palette)
        await pilot.pause()
        assert appT._transparent is True
        for w in (appT.editor, appT.preview_scroll, appT._header, appT._hints_general, appT._base_screen):
            assert w.has_class("transparent"), "transparence non appliquée à tout"
        assert "Transparency" in [c.title for c in appT.get_system_commands(appT.screen)], \
            "commande Transparency absente de la palette"
        appT.action_toggle_transparency()  # off
        await pilot.pause()
        assert appT._transparent is False
        for w in (appT.editor, appT.preview_scroll, appT._header, appT._hints_general, appT._base_screen):
            assert not w.has_class("transparent"), "transparence non retirée"

    # --- UI Splitmark: titres de bordure + numéros de ligne + indicateur ratio
    appS = SdfApp(path=str(doc))
    async with appS.run_test() as pilot:
        await pilot.pause()
        assert appS.editor.border_title.startswith("Editor:"), "titre éditeur manquant"
        assert appS.preview_scroll.border_title == "Preview", "titre preview manquant"
        assert appS.editor.show_line_numbers, "numéros de ligne désactivés"
        assert "[left]" in appS.editor.border_subtitle and "75/25" in appS.editor.border_subtitle
        await pilot.press("ctrl+w")  # ratio -> 50/50
        await pilot.pause()
        assert "50/50" in appS.editor.border_subtitle, "indicateur de ratio non mis à jour"
        # Ctrl+B fait tourner la rotation: left -> top
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert appS._rotation == 1 and "[top]" in appS.editor.border_subtitle, "rotation KO"
        await pilot.press("ctrl+b")  # -> right
        await pilot.pause()
        assert appS._rotation == 2 and "[right]" in appS.editor.border_subtitle
        await pilot.press("ctrl+b")  # -> bottom
        await pilot.pause()
        assert appS._rotation == 3 and "[bottom]" in appS.editor.border_subtitle
        await pilot.press("ctrl+b")  # -> left (tour complet)
        await pilot.pause()
        assert appS._rotation == 0, "la rotation doit revenir à left après un tour complet"

    # --- UI: pas d'emoji, pas de barre de recherche, palette centrée, Screenshot retiré
    from textual.command import CommandPalette, CommandList
    appU = SdfApp(path=str(doc))
    async with appU.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert "📄" not in appU.filetree.ICON_FILE, "emoji fichier toujours présent"
        assert "Screenshot" not in [c.title for c in appU.get_system_commands(appU.screen)]
        assert "—" not in appU.format_title("sdf", "notes.md auto").plain, "em dash dans le header"
        # palette ordonnée logiquement (Quit en dernier, pas alphabétique)
        from sdf.app import SdfCommands
        ordered = [c[0] for c in sorted(appU.get_system_commands(appU.screen),
                                        key=lambda c: (SdfCommands.rank(c[0]), c[0]))]
        assert ordered[-1] == "Quit", f"Quit doit être en dernier, ordre={ordered}"
        assert ordered.index("Theme") < ordered.index("Quit"), "Theme doit précéder Quit"
        assert "Maximize" not in ordered, "Maximize doit être retiré de la palette"
        await pilot.press("ctrl+p")
        for _ in range(4):
            await pilot.pause()
        pal = appU.screen
        assert isinstance(pal, CommandPalette)
        # barre de recherche masquée
        assert str(pal.query_one("#--input").styles.display) == "none", "barre de recherche visible"
        # liste centrée et bornée (pas pleine largeur)
        reg = pal.query_one(CommandList).region
        assert reg.x > 10 and reg.width < 100, "palette non centrée / pleine largeur"
        assert abs(reg.x - (120 - (reg.x + reg.width))) <= 2, "palette non centrée symétriquement"

    # --- Persistance ~/.config/sdf/ : un réglage runtime survit à un relancement
    import sdf.config as cfg
    prev_xdg = os.environ.get("XDG_CONFIG_HOME")
    os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="sdf_persist_")
    try:
        appP = SdfApp(path=str(doc))  # conflict par défaut = auto (config vierge)
        async with appP.run_test() as pilot:
            await pilot.pause()
            assert appP.conflict_mode == "auto"
            await pilot.press("ctrl+o")  # bascule en prompt -> persiste
            await pilot.pause()
            assert appP.conflict_mode == "prompt"
            appP.action_toggle_transparency()  # transparence on -> persiste
            await pilot.pause()
        assert cfg.config_path().exists(), "le fichier de config n'a pas été écrit"
        # relance: les réglages sont rechargés
        appP2 = SdfApp(path=str(doc))
        async with appP2.run_test() as pilot:
            await pilot.pause()
            assert appP2.conflict_mode == "prompt", "conflict_mode non persisté"
            assert appP2._transparent is True, "transparence non persistée"
    finally:
        if prev_xdg is not None:
            os.environ["XDG_CONFIG_HOME"] = prev_xdg

    # --- Fichier d'exemple intégré (sdf --example)
    from sdf.cli import _example_path
    ex = _example_path()
    assert Path(ex).exists(), "le fichier d'exemple n'a pas été matérialisé"
    appEx = SdfApp(path=ex)
    async with appEx.run_test() as pilot:
        await pilot.pause()
        assert "SDF example" in appEx.editor.text, "contenu de l'exemple non chargé"

    # --- Coloration syntaxique: natif (python) + langage du pack (ruby)
    (tmpdir / "s.py").write_text("import os\ndef f(x):\n    return x + 1\n", encoding="utf-8")
    (tmpdir / "s.rb").write_text("class A\n  def b; end\nend\n", encoding="utf-8")
    appL = SdfApp(path=str(tmpdir / "s.py"))
    async with appL.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert appL.editor.language == "python", "langage python non détecté"
        n = sum(len(v) for v in appL.editor._highlights.values())
        assert n > 0, "aucune coloration pour python"
        appL._load_file(tmpdir / "s.rb")
        await pilot.pause()
        assert appL.editor.language == "ruby", "langage ruby (pack) non enregistré"

    # --- Double Ctrl+C pour quitter
    appC = SdfApp(path=str(doc))
    async with appC.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert appC._quit_armed and appC.is_running, "1er ctrl+c doit armer sans quitter"
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert not appC.is_running, "2e ctrl+c doit quitter"

    # --- Opérations arbre: nouveau fichier, nouveau dossier, renommer
    from sdf.app import PromptScreen
    from textual.widgets import Input
    tdir = tmpdir / "ops"
    tdir.mkdir()
    (tdir / "a.md").write_text("# A\n", encoding="utf-8")
    appO = SdfApp(path=str(tdir / "a.md"))
    async with appO.run_test(size=(120, 34)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        appO.filetree.focus()
        await pilot.pause()
        # nouveau fichier
        await pilot.press("n")
        await pilot.pause()
        assert isinstance(appO.screen, PromptScreen)
        appO.screen.query_one(Input).value = "new.md"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert (tdir / "new.md").exists(), "nouveau fichier non créé"
        # nouveau dossier
        await pilot.press("d")
        await pilot.pause()
        appO.screen.query_one(Input).value = "sub"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert (tdir / "sub").is_dir(), "nouveau dossier non créé"
        # renommer le fichier ouvert
        appO.filetree.focus()
        for _ in range(6):
            cn = appO.filetree.cursor_node
            if cn and "a.md" in str(cn.label):
                break
            await pilot.press("down")
            await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        appO.screen.query_one(Input).value = "renamed.md"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert (tdir / "renamed.md").exists() and not (tdir / "a.md").exists(), "renommage KO"
        assert appO._path.name == "renamed.md", "le chemin ouvert ne suit pas le renommage"
        # Entrée sur un dossier entre dedans (nouvelle racine), Suppr remonte
        appO.filetree.focus()
        for _ in range(8):
            cn = appO.filetree.cursor_node
            if cn and cn.parent is not None and "sub" in str(cn.label):
                break
            await pilot.press("down")
            await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert Path(appO.filetree.path).name == "sub", "Entrée sur dossier n'entre pas dedans"
        await pilot.press("delete")  # Suppr = remonter
        await pilot.pause()
        await pilot.pause()
        assert Path(appO.filetree.path).name == "ops", "Suppr (remonter) KO"
        # la racine '..' est sélectionnable puis Entrée remonte encore
        appO.filetree.cursor_line = 0
        await pilot.pause()
        assert appO.filetree.cursor_node.parent is None, "la racine (..) doit être sélectionnable"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert Path(appO.filetree.path).name != "ops", "Entrée sur '..' doit remonter"

    # --- Scroll sync bidirectionnel + toggle + bordure focus
    long_md = "\n".join(f"## Section {i}\n\nParagraphe {i} de remplissage.\n" for i in range(40))
    (tmpdir / "long.md").write_text(long_md, encoding="utf-8")
    appSc = SdfApp(path=str(tmpdir / "long.md"))
    async with appSc.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.pause()
        pv = appSc.preview_scroll
        assert pv.max_scroll_y > 0, "la preview doit être défilable"
        # éditeur -> preview
        appSc.editor.move_cursor((39 * 3, 0))
        await pilot.pause()
        await pilot.pause()
        assert pv.scroll_y > 0, "la preview ne suit pas le scroll de l'éditeur"
        # preview -> éditeur (bidirectionnel)
        appSc.editor.scroll_to(y=0, animate=False)
        await pilot.pause()
        pv.scroll_to(y=pv.max_scroll_y * 0.8, animate=False)
        await pilot.pause()
        await pilot.pause()
        assert appSc.editor.scroll_y > 0, "l'éditeur ne suit pas le scroll de la preview"
        # indicateur de focus (bordure accent) quand l'éditeur est actif
        appSc.editor.focus()
        await pilot.pause()
        assert appSc.editor.has_focus, "l'éditeur doit avoir le focus (bordure accent)"
        # toggle off -> plus de sync
        appSc.action_toggle_scroll_sync()
        await pilot.pause()
        assert appSc._scroll_sync is False
        appSc.editor.scroll_to(y=0, animate=False)
        await pilot.pause()
        before = pv.scroll_y
        appSc.editor.scroll_to(y=appSc.editor.max_scroll_y, animate=False)
        await pilot.pause()
        await pilot.pause()
        assert abs(pv.scroll_y - before) < 1, "sync off: la preview ne doit pas bouger"
        # commande Scroll sync présente dans la palette
        assert any(c.title.startswith("Scroll sync") for c in appSc.get_system_commands(appSc.screen)), \
            "commande Scroll sync absente de la palette"

    # --- Task-lists: cases ✔/☐ SANS bullet redondant, listes normales/code intactes
    from sdf.app import _prettify_tasks
    src = ("- [x] fait\n- normal item\n- [ ] todo\n\n"
           "- alpha\n- beta\n\n```\n- [ ] dans code\n```\n")
    pretty = _prettify_tasks(src)
    plines = pretty.split("\n")
    assert plines[0].startswith("✔") and plines[2].startswith("☐"), f"cases KO: {pretty!r}"
    assert plines[1].startswith("•"), "l'item normal du bloc-tâche doit avoir un bullet glyphe"
    assert "[x]" not in pretty and "[ ] todo" not in pretty, "les crochets doivent disparaître"
    assert "- alpha" in pretty and "- beta" in pretty, "une liste normale ne doit pas être touchée"
    assert "- [ ] dans code" in pretty, "un bloc de code ne doit pas être transformé"
    (tmpdir / "task.md").write_text("- [x] fait\n- [ ] todo\n", encoding="utf-8")
    appT2 = SdfApp(path=str(tmpdir / "task.md"))
    async with appT2.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        assert "[x]" in appT2.editor.text, "l'éditeur doit garder le markdown brut des task-lists"

    # --- Preview conditionnelle: md -> preview, autre -> pas de preview, pdf -> read-only
    (tmpdir / "code.py").write_text("import os\nprint('hi')\n", encoding="utf-8")
    import pypdf
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with open(tmpdir / "doc.pdf", "wb") as fh:
        writer.write(fh)
    appPv = SdfApp(path=str(doc))  # doc = feat.md
    async with appPv.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        assert appPv._preview_kind == "markdown" and appPv.preview_scroll.display
        appPv._load_file(tmpdir / "code.py")
        await pilot.pause()
        assert appPv._preview_kind is None and not appPv.preview_scroll.display, \
            "la preview doit disparaître pour un fichier non-md"
        assert appPv.editor.display and not appPv.editor.read_only
        appPv._load_file(tmpdir / "doc.pdf")
        await pilot.pause()
        assert appPv._preview_kind == "pdf" and appPv.preview_scroll.display, "pdf doit garder un preview"
        assert appPv.editor.read_only, "un pdf doit être en lecture seule"
        assert appPv.action_save() is False, "sauver un pdf (read-only) doit être bloqué"

    # --- Indentation de masse: Tab indente toutes les lignes, Shift+Tab désindente
    from textual.widgets.text_area import Selection
    (tmpdir / "ind.py").write_text("aa\nbb\ncc\n", encoding="utf-8")
    appI = SdfApp(path=str(tmpdir / "ind.py"))
    async with appI.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        e = appI.editor
        e.focus()
        e.selection = Selection((0, 0), (2, 2))
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        assert e.text == "    aa\n    bb\n    cc\n", f"indent masse KO: {e.text!r}"
        await pilot.press("shift+tab")
        await pilot.pause()
        assert e.text == "aa\nbb\ncc\n", f"dedent masse KO: {e.text!r}"
        # toggle commentaire (python -> #)
        e.selection = Selection((0, 0), (2, 2))
        await pilot.pause()
        e.action_toggle_comment()
        await pilot.pause()
        assert e.text == "# aa\n# bb\n# cc\n", f"comment KO: {e.text!r}"
        e.action_toggle_comment()
        await pilot.pause()
        assert e.text == "aa\nbb\ncc\n", f"uncomment KO: {e.text!r}"
        # comment en COLONNE 0 sur du code indenté (pas après l'indentation)
        e.load_text("def f():\n    x = 1\n")
        e.selection = Selection((1, 0), (1, 5))
        await pilot.pause()
        e.action_toggle_comment()
        await pilot.pause()
        assert e.document.get_line(1) == "#     x = 1", f"comment pas en col 0: {e.document.get_line(1)!r}"
        e.selection = Selection((1, 0), (1, 5))
        await pilot.pause()
        e.action_toggle_comment()
        await pilot.pause()
        assert e.document.get_line(1) == "    x = 1", f"uncomment indenté KO: {e.document.get_line(1)!r}"
        e.load_text("aa\nbb\ncc\n")
        await pilot.pause()
        # langage inconnu -> pop-up de saisie du préfixe
        from sdf.app import PromptScreen as _PS
        from textual.widgets import Input as _Inp
        e._effective_language = lambda r: "brainfuck"
        e.load_text("hello\n")
        e.selection = Selection((0, 0), (0, 0))
        await pilot.pause()
        e.action_toggle_comment()
        await pilot.pause()
        assert isinstance(appI.screen, _PS), "langage inconnu doit ouvrir une pop-up"
        appI.screen.query_one(_Inp).value = "//"
        await pilot.press("enter")
        await pilot.pause()
        assert e.text == "// hello\n", f"préfixe custom KO: {e.text!r}"
        del e._effective_language  # restaure la méthode de classe
        e.load_text("aa\nbb\ncc\n")  # réinitialise pour le test suivant
        await pilot.pause()
        # delete line: curseur ligne bb -> supprime, curseur va sur la ligne du dessous
        e.selection = Selection((1, 0), (1, 0))
        await pilot.pause()
        e.action_delete_whole_line()
        await pilot.pause()
        assert e.text == "aa\ncc\n" and e.cursor_location == (1, 0), f"delete line KO: {e.text!r}"
        # focus arbre -> contour sidebar jaune
        await pilot.press("ctrl+e")
        await pilot.pause()
        appI.filetree.focus()
        await pilot.pause()
        assert appI.filetree.has_focus, "l'arbre doit avoir le focus (sidebar en accent via :focus-within)"
        # undo / redo sur Ctrl+Z / Ctrl+Shift+Z
        e.focus()
        await pilot.pause()
        e.insert("ZZZ")
        await pilot.pause()
        await pilot.press("ctrl+z")
        await pilot.pause()
        assert "ZZZ" not in e.text, f"ctrl+z (undo) KO: {e.text!r}"
        await pilot.press("ctrl+shift+z")
        await pilot.pause()
        assert "ZZZ" in e.text, f"ctrl+shift+z (redo) KO: {e.text!r}"
        # auto-surround: sélection + caractère d'entourage -> entoure (pas remplace)
        e.load_text("hello test world\n")
        e.selection = Selection((0, 6), (0, 10))  # "test"
        await pilot.pause()
        await pilot.press("*")
        await pilot.pause()
        assert e.text == "hello *test* world\n", f"surround 1 KO: {e.text!r}"
        await pilot.press("*")  # cycle -> gras
        await pilot.pause()
        assert e.text == "hello **test** world\n", f"surround gras KO: {e.text!r}"
        await pilot.press("*")  # cycle -> retire
        await pilot.pause()
        assert e.text == "hello test world\n", f"surround retrait KO: {e.text!r}"
        e.load_text("hello test\n")
        e.selection = Selection((0, 6), (0, 10))
        await pilot.pause()
        await pilot.press("`")
        await pilot.pause()
        assert e.text == "hello `test`\n", f"surround code KO: {e.text!r}"
        # caractère de fermeture entoure aussi, et re-tape retire (paire = toggle)
        e.load_text("hello test\n")
        e.selection = Selection((0, 6), (0, 10))
        await pilot.pause()
        await pilot.press(")")
        await pilot.pause()
        assert e.text == "hello (test)\n", f"surround fermeture KO: {e.text!r}"
        await pilot.press(")")
        await pilot.pause()
        assert e.text == "hello test\n", f"toggle paire KO: {e.text!r}"

    # --- Soft line breaks: un simple retour à la ligne devient un vrai saut (hardbreak)
    from sdf.app import _md_parser
    toks = _md_parser().parse("a\nb\n")
    kinds = [c.type for t in toks if getattr(t, "children", None) for c in t.children]
    assert "hardbreak" in kinds and "softbreak" not in kinds, f"softbreak non converti: {kinds}"

    # --- Commentaire markdown: bloc de code -> syntaxe du langage, texte -> <!-- -->
    (tmpdir / "mix.md").write_text("texte\n\n```python\nx = 1\n```\n", encoding="utf-8")
    appMc = SdfApp(path=str(tmpdir / "mix.md"))
    async with appMc.run_test(size=(100, 25)) as pilot:
        await pilot.pause()
        em = appMc.editor
        assert em._effective_language(3) == "python", "ligne dans un bloc python -> python"
        assert em._effective_language(0) == "markdown", "texte hors bloc -> markdown"
        em.focus()
        em.selection = Selection((3, 0), (3, 0))  # x = 1
        await pilot.pause()
        em.action_toggle_comment()
        await pilot.pause()
        assert em.document.get_line(3) == "# x = 1", f"bloc code doit commenter en #: {em.document.get_line(3)!r}"
        em.selection = Selection((0, 0), (0, 0))  # texte
        await pilot.pause()
        em.action_toggle_comment()
        await pilot.pause()
        assert em.document.get_line(0) == "<!-- texte -->", f"texte md -> HTML: {em.document.get_line(0)!r}"

    # --- Cyclage de focus entre panneaux + Échap depuis la preview
    appFc = SdfApp(path=str(doc))
    async with appFc.run_test(size=(100, 25)) as pilot:
        await pilot.pause()

        def focused_panel():
            fo = appFc.focused
            for name, w in (("editor", appFc.editor), ("preview", appFc.preview_scroll),
                            ("tree", appFc.filetree)):
                if fo is not None and w in fo.ancestors_with_self:
                    return name
            return None

        appFc.editor.focus()
        await pilot.pause()
        appFc.action_cycle_focus()
        await pilot.pause()
        assert focused_panel() == "preview", "cycle focus editor -> preview KO"
        appFc.action_cycle_focus()
        await pilot.pause()
        assert focused_panel() == "editor", "cycle focus preview -> editor KO"
        # Échap depuis la preview ne reste pas coincé
        appFc.preview_scroll.focus()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert focused_panel() == "editor", "Échap depuis preview doit revenir à l'éditeur"


if __name__ == "__main__":
    asyncio.run(_run_all())
