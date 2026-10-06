"""
chat.py – Terminal-Chat für die Vorführung.

Start:  python chat.py
Beenden: exit
"""

import json

from harness import erstellen


def freigabe_im_terminal(werkzeug: str, eingabe: dict, vorschau: dict) -> tuple[bool, str]:
    """Human-in-the-Loop: Der Mensch sieht das Dokument und entscheidet."""
    print("\n" + "=" * 60)
    print(f"FREIGABE ERFORDERLICH: {werkzeug}")
    print(json.dumps(vorschau, ensure_ascii=False, indent=2))
    print("=" * 60)
    antwort = input("Freigeben? [j/n] ").strip().lower()
    if antwort == "j":
        return True, ""
    return False, input("Grund (optional): ").strip()


def main() -> None:
    harness = erstellen(approver=freigabe_im_terminal)
    print("Kundenservice-Agent der Muster Bürobedarf GmbH. 'exit' zum Beenden.\n")
    while True:
        try:
            text = input("Sie: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in {"exit", "quit"}:
            break
        if text:
            print(f"\nAgent: {harness.antworten(text)}\n")


if __name__ == "__main__":
    main()
