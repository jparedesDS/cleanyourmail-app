"""Release docs must describe the fail-safe updater and the settings contract.

Every README is checked so a corrected English sentence cannot drift back in a
translation. The claims here are the ones the final review found false: the old
installer-failure fallback, the request count and the omitted update timestamp.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
READMES = sorted(ROOT.glob("README*.md"))

OLD_INSTALLER_FAILURE_CLAIMS = (
    "If the installer cannot finish, the old app reopens and the banner offers "
    "Open GitHub.",
    "Si el instalador no termina, la app anterior se vuelve a abrir y el aviso "
    "ofrece Abrir GitHub.",
    "Wenn der Installer nicht abschließt, öffnet sich die alte App wieder und "
    "das Banner bietet Open GitHub an.",
    "Si l'installateur n'aboutit pas, l'ancienne app se rouvre et la bannière "
    "propose Open GitHub.",
    "Se l'installer non termina, la vecchia app si riapre e il banner propone "
    "Open GitHub.",
    "Se o instalador não concluir, o app antigo reabre e o banner oferece "
    "Open GitHub.",
    "インストーラーが完了しない場合、以前のアプリが再起動し、バナーに "
    "Open GitHub が表示されます。",
    "설치 프로그램이 완료되지 않으면 이전 앱이 다시 열리고 배너에 "
    "Open GitHub가 표시됩니다.",
    "如果安装程序未能完成，旧版应用会重新打开，横幅会提供 Open GitHub。",
    "如果安裝程式未能完成，舊版應用程式會重新開啟，橫幅會提供 Open GitHub。",
)

START_FAILURE_BY_README = {
    "README.md": "If the update helper cannot start",
    "README.es.md": "Si el asistente de actualización no puede iniciarse",
    "README.de.md": "Kann der Update-Helfer nicht starten",
    "README.fr.md": "Si l’assistant de mise à jour ne peut pas démarrer",
    "README.it.md": "Se l'helper di aggiornamento non può partire",
    "README.pt-BR.md": "Se o assistente de atualização não puder iniciar",
    "README.ja.md": "更新ヘルパーを開始できない場合",
    "README.ko.md": "업데이트 도우미를 시작할 수 없으면",
    "README.zh-CN.md": "如果更新助手无法启动",
    "README.zh-TW.md": "如果更新助手無法啟動",
}


def _flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split()).replace("**", "")


@pytest.mark.parametrize("readme", READMES, ids=lambda path: path.name)
def test_every_readme_describes_the_installer_failures_accurately(readme):
    text = _flat(readme)

    for old_claim in OLD_INSTALLER_FAILURE_CLAIMS:
        assert old_claim not in text, f"stale installer-failure claim in {readme.name}"
    assert "GitHub" in text
    assert START_FAILURE_BY_README[readme.name] in text, (
        f"missing start-failure fallback in {readme.name}"
    )


def test_the_readme_project_layout_names_the_auto_update_spec():
    assert "0.6.0 auto-update" in _flat(ROOT / "README.md")


def test_security_docs_count_the_confirmed_update_assets():
    for relative in (
        "README.md",
        "SECURITY.md",
        "docs/ARCHITECTURE.md",
        "docs/THREAT_MODEL.md",
    ):
        text = _flat(ROOT / relative).lower()
        assert "two requests" not in text, relative
        assert "two public" in text, relative


def test_security_docs_mention_the_last_update_check_in_settings():
    architecture = _flat(ROOT / "docs" / "ARCHITECTURE.md").lower()
    threat_model = _flat(ROOT / "docs" / "THREAT_MODEL.md").lower()

    assert "last_update_check" in architecture
    assert "last_update_check" in threat_model


def test_architecture_documents_the_helper_handshake_and_system32_tools():
    text = _flat(ROOT / "docs" / "ARCHITECTURE.md").lower()

    assert "start marker" in text
    assert "system32" in text
