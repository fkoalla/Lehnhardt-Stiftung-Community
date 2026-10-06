"""
agent.py – Was der Agent IST: Modell, System-Prompt und Werkzeug-Beschreibungen.

Der Agent selbst enthält keine Logik. Er bekommt nur Beschreibungen der
Werkzeuge (JSON-Schema). Was die Werkzeuge tatsächlich tun, steht in tools.py,
und wer sie wann ausführen darf, entscheidet harness.py.
"""

MODEL = "claude-opus-5-5"
EFFORT = "medium"     # Denktiefe: low | medium | high | xhigh | max
MAX_TOKENS = 16000

SYSTEM_PROMPT = """\
Du bist der Kundenservice-Agent der Muster Bürobedarf GmbH, eines Großhändlers für Bürobedarf.
Du hilfst Mitarbeitenden im Innendienst, Kundenanfragen zu bearbeiten und daraus Angebote,
Auftragsbestätigungen und Lieferscheine zu erstellen.

So arbeitest du:
- Die Dokumentkette ist immer Angebot → Auftragsbestätigung → Lieferschein. Eine
  Auftragsbestätigung entsteht nur aus einem bestehenden Angebot, ein Lieferschein nur aus
  einer bestehenden Auftragsbestätigung.
- Ermittle zuerst den Kunden (kunde_suchen). Lege nur dann einen neuen an, wenn es ihn wirklich
  nicht gibt und alle Pflichtangaben vorliegen.
- Ordne jeden Kundenwunsch über artikel_suchen einer Artikelnummer aus dem Katalog zu.
  Ist ein Wunsch mehrdeutig (z. B. „Ordner“ ohne Breite) oder gibt es keinen passenden Artikel,
  frag nach, statt zu raten oder Artikel zu erfinden.
- Fehlt eine Menge, frag nach. Rechne nie selbst: Preise, Rabatte, Mehrwertsteuer und Summen
  liefert ausschließlich das Werkzeug. Gib Beträge genau so wieder, wie das Werkzeug sie liefert.
- Prüfe bei Angeboten den Lagerbestand und weise auf Engpässe hin; ein Angebot ist trotzdem möglich.
- Neue Dokumente sind Entwürfe. Versende ein Dokument nur, wenn der Mitarbeiter das ausdrücklich
  möchte. Vor dem Versand und vor jeder Auftragsbestätigung fragt das System einen Menschen um
  Freigabe; wird sie verweigert, akzeptiere das und frag, was geändert werden soll.
- Meldet ein Werkzeug einen Fehler, erkläre ihn knapp und schlag den nächsten sinnvollen Schritt vor.
  Umgehe Fehler nicht durch Raten.

Antworte auf Deutsch, sachlich und knapp. Nenne nach jeder Dokumenterstellung Dokumentnummer,
Positionen und Summen.
"""


def _tool(name: str, beschreibung: str, eigenschaften: dict, pflicht: list[str]) -> dict:
    """Baut eine Tool-Definition. strict=True sorgt dafür, dass die Eingaben des
    Modells exakt dem Schema entsprechen (keine fehlenden oder erfundenen Felder)."""
    return {
        "name": name,
        "description": beschreibung,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": eigenschaften,
            "required": pflicht,
            "additionalProperties": False,
        },
    }


_TEXT = {"type": "string"}

TOOLS = [
    _tool("kunde_suchen",
          "Sucht Kunden nach Kundennummer, Firmenname, Ansprechpartner oder E-Mail (Teilstring genügt).",
          {"suchbegriff": _TEXT}, ["suchbegriff"]),
    _tool("kunde_anlegen",
          "Legt einen neuen Kunden an. Nur verwenden, wenn kunde_suchen nichts gefunden hat.",
          {"name": _TEXT, "ansprechpartner": _TEXT, "strasse": _TEXT, "ort": {"type": "string", "description": "PLZ und Ort"},
           "email": _TEXT},
          ["name", "ansprechpartner", "strasse", "ort", "email"]),
    _tool("artikel_suchen",
          "Durchsucht den Katalog. Alle Suchwörter müssen in Artikelnummer oder Bezeichnung vorkommen. "
          "Liefert Artikelnummer, Bezeichnung, Einheit und Listenpreis. Mit kurzen Suchwörtern suchen, z. B. 'ordner' oder 'toner'.",
          {"suchbegriff": _TEXT}, ["suchbegriff"]),
    _tool("lagerbestand_pruefen",
          "Gibt den verfügbaren Lagerbestand eines Artikels zurück.",
          {"artikelnr": _TEXT}, ["artikelnr"]),
    _tool("angebot_erstellen",
          "Erstellt ein Angebot (Entwurf) mit fortlaufender Nummer. Preise, Rabatte und Summen berechnet das System.",
          {"kundennr": _TEXT,
           "positionen": {"type": "array", "items": {
               "type": "object",
               "properties": {"artikelnr": _TEXT, "menge": {"type": "integer"}},
               "required": ["artikelnr", "menge"], "additionalProperties": False}},
           "bemerkung": {"type": "string", "description": "Optionaler Freitext für das Dokument, sonst leer."}},
          ["kundennr", "positionen", "bemerkung"]),
    _tool("auftrag_bestaetigen",
          "Wandelt ein angenommenes Angebot in eine Auftragsbestätigung um. Erfordert menschliche Freigabe.",
          {"angebotsnr": _TEXT,
           "bestellreferenz": {"type": "string", "description": "Bestellnummer des Kunden, falls genannt, sonst leer."}},
          ["angebotsnr", "bestellreferenz"]),
    _tool("lieferschein_erstellen",
          "Erstellt den Lieferschein zu einer Auftragsbestätigung und bucht den Lagerbestand ab.",
          {"auftragsnr": _TEXT}, ["auftragsnr"]),
    _tool("dokument_anzeigen",
          "Zeigt ein vorhandenes Dokument (Angebot, Auftragsbestätigung oder Lieferschein) an.",
          {"dokumentnr": _TEXT}, ["dokumentnr"]),
    _tool("dokument_versenden",
          "Erzeugt das PDF und versendet das Dokument an den Kunden. Erfordert menschliche Freigabe.",
          {"dokumentnr": _TEXT}, ["dokumentnr"]),
]

# Diese Werkzeuge haben Wirkung nach außen bzw. sind verbindlich.
# Der Harness führt sie nur nach Freigabe durch einen Menschen aus.
FREIGABE_PFLICHTIG = {"auftrag_bestaetigen", "dokument_versenden"}
