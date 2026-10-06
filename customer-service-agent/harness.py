"""
harness.py – Alles um das Modell herum.

Der Harness ist der Teil, der aus einem Sprachmodell einen verlässlichen Agenten macht:

  1. Agent-Schleife    Modell aufrufen → Tool-Aufrufe ausführen → Ergebnisse zurückgeben
                       → wiederholen, bis das Modell eine fertige Antwort liefert.
  2. Validierung       Jede Tool-Eingabe wird gegen das Schema geprüft, bevor Code läuft.
  3. Freigabe (HITL)   Verbindliche oder nach außen wirkende Aktionen brauchen ein OK
                       von einem Menschen.
  4. Zustand           Dokumente und Nummernkreise liegen im Store und werden gespeichert.
  5. Logging           Jeder Modellaufruf und jeder Tool-Aufruf landet im Audit-Log (JSONL).
  6. Leitplanken       Maximale Schrittzahl, Fehlerbehandlung, Umgang mit Abbruchgründen.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from agent import EFFORT, FREIGABE_PFLICHTIG, MAX_TOKENS, MODEL, SYSTEM_PROMPT, TOOLS
from tools import Store, ToolError, Toolbox

# Signatur der Freigabe-Funktion: (werkzeug, eingabe, vorschau) → (freigegeben?, kommentar)
Approver = Callable[[str, dict, dict], tuple[bool, str]]


class AuditLog:
    """Schreibt jedes Ereignis als eine JSON-Zeile – nachvollziehbar und maschinenlesbar."""

    def __init__(self, pfad: Path | None = None):
        self.pfad = pfad
        self.eintraege: list[dict] = []
        if pfad:
            pfad.parent.mkdir(parents=True, exist_ok=True)

    def schreiben(self, sitzung: str, ereignis: str, **daten) -> None:
        eintrag = {"zeit": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "sitzung": sitzung, "ereignis": ereignis, **daten}
        self.eintraege.append(eintrag)
        if self.pfad:
            with self.pfad.open("a", encoding="utf-8") as f:
                f.write(json.dumps(eintrag, ensure_ascii=False, default=str) + "\n")


def eingabe_validieren(name: str, eingabe: object) -> None:
    """Prüft eine Tool-Eingabe gegen das Schema aus agent.py.
    strict=True erzwingt das bereits auf API-Seite; der Harness prüft trotzdem selbst,
    denn er darf keiner Eingabe von außen blind vertrauen."""
    schema = next((t["input_schema"] for t in TOOLS if t["name"] == name), None)
    if schema is None:
        raise ToolError(f"Unbekanntes Werkzeug: {name}")
    _pruefen(eingabe, schema, pfad=name)


def _pruefen(wert: object, schema: dict, pfad: str) -> None:
    typ = schema["type"]
    if typ == "object":
        if not isinstance(wert, dict):
            raise ToolError(f"{pfad}: Objekt erwartet.")
        fehlend = [k for k in schema["required"] if k not in wert]
        zuviel = [k for k in wert if k not in schema["properties"]]
        if fehlend:
            raise ToolError(f"{pfad}: Pflichtfelder fehlen: {', '.join(fehlend)}")
        if zuviel:
            raise ToolError(f"{pfad}: Unbekannte Felder: {', '.join(zuviel)}")
        for k, v in wert.items():
            _pruefen(v, schema["properties"][k], f"{pfad}.{k}")
    elif typ == "array":
        if not isinstance(wert, list):
            raise ToolError(f"{pfad}: Liste erwartet.")
        for i, v in enumerate(wert):
            _pruefen(v, schema["items"], f"{pfad}[{i}]")
    elif typ == "string" and not isinstance(wert, str):
        raise ToolError(f"{pfad}: Text erwartet.")
    elif typ == "integer" and (not isinstance(wert, int) or isinstance(wert, bool)):
        raise ToolError(f"{pfad}: Ganze Zahl erwartet.")


class Harness:
    def __init__(self, client, toolbox: Toolbox, approver: Approver,
                 log: AuditLog | None = None, store_pfad: Path | None = None, max_schritte: int = 15):
        self.client = client
        self.toolbox = toolbox
        self.approver = approver
        self.log = log or AuditLog()
        self.store_pfad = store_pfad
        self.max_schritte = max_schritte
        self.sitzung = uuid.uuid4().hex[:8]
        self.messages: list[dict] = []   # Gesprächsverlauf, wird nur angehängt, nie umgeschrieben

    # ------------------------------------------------------------------
    # 1. Die Agent-Schleife
    # ------------------------------------------------------------------

    def antworten(self, nutzertext: str) -> str:
        self.messages.append({"role": "user", "content": nutzertext})
        self.log.schreiben(self.sitzung, "nutzer", text=nutzertext)

        for schritt in range(1, self.max_schritte + 1):
            antwort = self._modell_aufrufen()
            # Die Antwort unverändert anhängen (inkl. Denk-Blöcken) – die API verlangt das.
            self.messages.append({"role": "assistant", "content": antwort.content})
            self.log.schreiben(self.sitzung, "modell", schritt=schritt, stop_reason=antwort.stop_reason,
                               tokens=_tokens(antwort))

            if antwort.stop_reason == "tool_use":
                ergebnisse = [self._werkzeug_ausfuehren(b) for b in antwort.content if b.type == "tool_use"]
                # Alle Ergebnisse gemeinsam in EINER Nachricht zurückgeben.
                self.messages.append({"role": "user", "content": ergebnisse})
                continue
            if antwort.stop_reason == "pause_turn":
                continue
            if antwort.stop_reason == "refusal":
                text = "Diese Anfrage kann ich nicht bearbeiten."
            elif antwort.stop_reason == "max_tokens":
                text = _text(antwort) + "\n[Antwort wurde wegen Längenbegrenzung abgeschnitten.]"
            else:  # end_turn
                text = _text(antwort)
            self.log.schreiben(self.sitzung, "agent", text=text)
            return text

        # Leitplanke: Ein Agent, der sich im Kreis dreht, wird gestoppt.
        self.log.schreiben(self.sitzung, "abbruch", grund="max_schritte")
        return f"Abgebrochen: mehr als {self.max_schritte} Arbeitsschritte. Bitte Anfrage präzisieren."

    def _modell_aufrufen(self):
        # fallbacks="default": Lehnt das Modell eine Anfrage aus Sicherheitsgründen ab,
        # beantwortet die API sie automatisch mit einem passenden Ersatzmodell.
        return self.client.beta.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=self.messages,
            thinking={"type": "adaptive"},
            output_config={"effort": EFFORT},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

    # ------------------------------------------------------------------
    # 2.–5. Validierung, Freigabe, Ausführung, Zustand, Logging
    # ------------------------------------------------------------------

    def _werkzeug_ausfuehren(self, block) -> dict:
        name, eingabe = block.name, block.input
        start = time.perf_counter()
        try:
            eingabe_validieren(name, eingabe)

            if name in FREIGABE_PFLICHTIG:
                vorschau = self._vorschau(name, eingabe)
                ok, kommentar = self.approver(name, eingabe, vorschau)
                self.log.schreiben(self.sitzung, "freigabe", werkzeug=name, eingabe=eingabe,
                                   freigegeben=ok, kommentar=kommentar)
                if not ok:
                    return self._ergebnis(block, name, eingabe, start, fehler=(
                        "Freigabe durch Mitarbeiter verweigert."
                        + (f" Kommentar: {kommentar}" if kommentar else "")
                        + " Aktion wurde NICHT ausgeführt."))

            resultat = getattr(self.toolbox, name)(**eingabe)
            if self.store_pfad:
                self.toolbox.store.speichern(self.store_pfad)
            return self._ergebnis(block, name, eingabe, start, resultat=resultat)

        except ToolError as e:
            return self._ergebnis(block, name, eingabe, start, fehler=str(e))
        except Exception as e:  # Programmfehler: protokollieren, aber das Modell nicht mit Details füttern
            self.log.schreiben(self.sitzung, "interner_fehler", werkzeug=name, fehler=repr(e))
            return self._ergebnis(block, name, eingabe, start, fehler="Interner Fehler im Werkzeug. Bitte Mitarbeiter informieren.")

    def _vorschau(self, name: str, eingabe: dict) -> dict:
        """Was der Mensch vor der Freigabe zu sehen bekommt."""
        nr = eingabe.get("dokumentnr") or eingabe.get("angebotsnr")
        try:
            return self.toolbox.dokument_anzeigen(nr)
        except ToolError as e:
            return {"hinweis": str(e)}

    def _ergebnis(self, block, name, eingabe, start, resultat=None, fehler=None) -> dict:
        self.log.schreiben(self.sitzung, "werkzeug", werkzeug=name, eingabe=eingabe,
                           ok=fehler is None, fehler=fehler, resultat=resultat,
                           dauer_ms=round((time.perf_counter() - start) * 1000, 1))
        inhalt = json.dumps(resultat, ensure_ascii=False) if fehler is None else f"FEHLER: {fehler}"
        return {"type": "tool_result", "tool_use_id": block.id, "content": inhalt,
                **({"is_error": True} if fehler else {})}


def _text(antwort) -> str:
    return "\n".join(b.text for b in antwort.content if b.type == "text").strip()


def _tokens(antwort) -> dict | None:
    u = getattr(antwort, "usage", None)
    return {"input": u.input_tokens, "output": u.output_tokens} if u else None


def erstellen(client=None, approver: Approver | None = None, datenordner: Path = Path("daten")) -> Harness:
    """Baut einen einsatzbereiten Harness mit Persistenz und Audit-Log."""
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    store_pfad = datenordner / "store.json"
    toolbox = Toolbox(Store.laden(store_pfad), pdf_ordner=datenordner / "pdf")
    return Harness(client, toolbox, approver or (lambda *_: (False, "kein Freigeber konfiguriert")),
                   log=AuditLog(datenordner / "audit.jsonl"), store_pfad=store_pfad)
