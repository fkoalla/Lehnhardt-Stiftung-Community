"""
tools.py – Fachlogik des Customer-Service-Agenten.

Hier liegen Katalog, Kunden, Lager und die Dokumentkette
Angebot (AN) → Auftragsbestätigung (AB) → Lieferschein (LS).

Grundprinzip: Das Sprachmodell rechnet NIE. Es übergibt nur Artikelnummern
und Mengen. Preise, Rabatte, MwSt. und Summen werden ausschließlich hier
im Code berechnet (mit Decimal, also ohne Rundungsfehler von float).
Jede fachliche Regelverletzung löst einen ToolError aus. Der Harness gibt
diesen Fehler an das Modell zurück, damit es nachfragen oder korrigieren kann.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

# ---------------------------------------------------------------------------
# Stammdaten (fiktiver Großhändler)
# ---------------------------------------------------------------------------

FIRMA = {
    "name": "Muster Bürobedarf GmbH",
    "strasse": "Industriestraße 12",
    "ort": "50667 Köln",
    "telefon": "+49 221 123456-0",
    "email": "vertrieb@muster-buero.example",
    "ust_id": "DE123456789",
}

MWST_SATZ = Decimal("0.19")
ANGEBOT_GUELTIG_TAGE = 30
MAX_MENGE_PRO_POSITION = 10_000

# Staffelrabatt nach Menge pro Position: ab Menge → Rabatt
STAFFELRABATT = [(100, Decimal("0.10")), (50, Decimal("0.05"))]

KATALOG = {
    "PAP-A4-500": {"bezeichnung": "Kopierpapier A4, 80 g/m², 500 Blatt", "einheit": "Pack", "preis": Decimal("4.90")},
    "PAP-A3-500": {"bezeichnung": "Kopierpapier A3, 80 g/m², 500 Blatt", "einheit": "Pack", "preis": Decimal("9.80")},
    "ORD-80-BL":  {"bezeichnung": "Ordner A4, 80 mm, blau", "einheit": "Stück", "preis": Decimal("2.49")},
    "ORD-50-SW":  {"bezeichnung": "Ordner A4, 50 mm, schwarz", "einheit": "Stück", "preis": Decimal("2.29")},
    "KUG-BL-10":  {"bezeichnung": "Kugelschreiber blau, 10er-Pack", "einheit": "Pack", "preis": Decimal("3.95")},
    "TON-HP-26X": {"bezeichnung": "Toner HP 26X, schwarz", "einheit": "Stück", "preis": Decimal("129.00")},
    "HEF-24-6":   {"bezeichnung": "Heftgerät 24/6, bis 30 Blatt", "einheit": "Stück", "preis": Decimal("12.50")},
    "MON-27-4K":  {"bezeichnung": "Monitor 27 Zoll, 4K, höhenverstellbar", "einheit": "Stück", "preis": Decimal("349.00")},
    "STU-ERGO-1": {"bezeichnung": "Bürostuhl ergonomisch, Modell Ergo 1", "einheit": "Stück", "preis": Decimal("289.00")},
    "TIS-HV-160": {"bezeichnung": "Schreibtisch höhenverstellbar, 160×80 cm", "einheit": "Stück", "preis": Decimal("549.00")},
    # Preis None = kein Preis hinterlegt. Das System rechnet dann nie mit einem Ersatzwert,
    # sondern verlangt, dass der Preis beim Mitarbeiter erfragt und im Katalog gepflegt wird.
    "MUS-NEU-01": {"bezeichnung": "Neuheit Muster, Preis noch nicht festgelegt", "einheit": "Stück", "preis": None},
}

START_LAGER = {"MUS-NEU-01": 5, 
    "PAP-A4-500": 2000, "PAP-A3-500": 150, "ORD-80-BL": 800, "ORD-50-SW": 600,
    "KUG-BL-10": 400, "TON-HP-26X": 25, "HEF-24-6": 120, "MON-27-4K": 12,
    "STU-ERGO-1": 8, "TIS-HV-160": 0,
}

START_KUNDEN = {
    "K-1001": {"name": "Schmidt Steuerberatung", "ansprechpartner": "Anna Schmidt",
               "strasse": "Hauptstraße 5", "ort": "50667 Köln",
               "email": "a.schmidt@schmidt-stb.example", "rabatt": Decimal("0.03")},
    "K-1002": {"name": "Praxis Dr. Weber", "ansprechpartner": "Dr. Jonas Weber",
               "strasse": "Ringstraße 18", "ort": "53111 Bonn",
               "email": "praxis@dr-weber.example", "rabatt": Decimal("0.00")},
    "K-1003": {"name": "Becker Logistik AG", "ansprechpartner": "Mira Becker",
               "strasse": "Hafenweg 2", "ort": "47051 Duisburg",
               "email": "einkauf@becker-logistik.example", "rabatt": Decimal("0.05")},
}


class ToolError(Exception):
    """Fachlicher Fehler. Die Meldung geht als Tool-Ergebnis zurück an das Modell."""


def geld(betrag: Decimal) -> Decimal:
    """Kaufmännisch auf Cent runden."""
    return betrag.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fmt(betrag: Decimal) -> str:
    """Deutsches Zahlenformat: 1.234,56 €"""
    s = f"{geld(betrag):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"


# ---------------------------------------------------------------------------
# Zustand: Kunden, Lager, Dokumente, Nummernkreise
# ---------------------------------------------------------------------------

@dataclass
class Store:
    kunden: dict = field(default_factory=lambda: copy.deepcopy(START_KUNDEN))
    lager: dict = field(default_factory=lambda: dict(START_LAGER))
    dokumente: dict = field(default_factory=dict)   # Nummer → Dokument
    zaehler: dict = field(default_factory=dict)     # "AN-2026" → letzte Nummer
    heute: date = field(default_factory=date.today)

    def naechste_nummer(self, praefix: str) -> str:
        """Fortlaufende Nummer pro Dokumentart und Jahr, z. B. AN-2026-0001."""
        schluessel = f"{praefix}-{self.heute.year}"
        self.zaehler[schluessel] = self.zaehler.get(schluessel, 0) + 1
        return f"{schluessel}-{self.zaehler[schluessel]:04d}"

    # Einfache Persistenz als JSON, damit Dokumente einen Neustart überleben.
    def speichern(self, pfad: Path) -> None:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        daten = {"kunden": self.kunden, "lager": self.lager,
                 "dokumente": self.dokumente, "zaehler": self.zaehler}
        pfad.write_text(json.dumps(daten, default=str, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def laden(cls, pfad: Path) -> "Store":
        if not pfad.exists():
            return cls()
        d = json.loads(pfad.read_text(encoding="utf-8"))
        for k in d["kunden"].values():
            k["rabatt"] = Decimal(k["rabatt"])
        return cls(kunden=d["kunden"], lager=d["lager"], dokumente=d["dokumente"], zaehler=d["zaehler"])


# ---------------------------------------------------------------------------
# Werkzeuge – jede öffentliche Methode entspricht einem Tool des Agenten
# ---------------------------------------------------------------------------

class Toolbox:
    def __init__(self, store: Store, pdf_ordner: Path = Path("ausgabe")):
        self.store = store
        self.pdf_ordner = pdf_ordner

    # --- Kunden -----------------------------------------------------------

    def kunde_suchen(self, suchbegriff: str) -> dict:
        s = suchbegriff.strip().lower()
        if not s:
            raise ToolError("Suchbegriff ist leer.")
        treffer = [
            {"kundennr": nr, "name": k["name"], "ansprechpartner": k["ansprechpartner"],
             "ort": k["ort"], "email": k["email"]}
            for nr, k in self.store.kunden.items()
            if s in nr.lower() or s in k["name"].lower()
            or s in k["ansprechpartner"].lower() or s in k["email"].lower()
        ]
        return {"anzahl": len(treffer), "kunden": treffer}

    def kunde_anlegen(self, name: str, ansprechpartner: str, strasse: str, ort: str, email: str) -> dict:
        werte = {"name": name, "ansprechpartner": ansprechpartner, "strasse": strasse, "ort": ort, "email": email}
        fehlend = [k for k, v in werte.items() if not v.strip()]
        if fehlend:
            raise ToolError(f"Pflichtfelder fehlen: {', '.join(fehlend)}. Bitte beim Kunden erfragen.")
        if "@" not in email:
            raise ToolError(f"Ungültige E-Mail-Adresse: {email}")
        for nr, k in self.store.kunden.items():
            if k["name"].lower() == name.strip().lower():
                raise ToolError(f"Kunde existiert bereits als {nr}. Bitte diese Kundennummer verwenden.")
        nr = f"K-{1001 + len(self.store.kunden)}"
        self.store.kunden[nr] = {**{k: v.strip() for k, v in werte.items()}, "rabatt": Decimal("0")}
        return {"kundennr": nr, "angelegt": True}

    def _kunde(self, kundennr: str) -> dict:
        if kundennr not in self.store.kunden:
            raise ToolError(f"Kunde {kundennr} existiert nicht. Erst mit kunde_suchen prüfen oder kunde_anlegen.")
        return self.store.kunden[kundennr]

    # --- Katalog & Lager --------------------------------------------------

    def artikel_suchen(self, suchbegriff: str) -> dict:
        woerter = suchbegriff.lower().split()
        treffer = [
            {"artikelnr": nr, "bezeichnung": a["bezeichnung"], "einheit": a["einheit"],
             "listenpreis_netto": fmt(a["preis"]) if a["preis"] is not None else "NICHT HINTERLEGT"}
            for nr, a in KATALOG.items()
            if all(w in (nr + " " + a["bezeichnung"]).lower() for w in woerter)
        ]
        hinweis = None if treffer else "Kein Artikel gefunden. Nichts erfinden – beim Kunden nachfragen."
        if any(a["listenpreis_netto"] == "NICHT HINTERLEGT" for a in treffer):
            hinweis = "Für mindestens einen Artikel ist kein Preis hinterlegt. Preis nicht schätzen, Mitarbeiter fragen."
        return {"anzahl": len(treffer), "artikel": treffer, "hinweis": hinweis}

    def lagerbestand_pruefen(self, artikelnr: str) -> dict:
        self._artikel(artikelnr)
        return {"artikelnr": artikelnr, "verfuegbar": self.store.lager.get(artikelnr, 0)}

    def _artikel(self, artikelnr: str) -> dict:
        # Die zentrale Sperre gegen Halluzinationen: nur Katalogartikel sind erlaubt.
        if artikelnr not in KATALOG:
            raise ToolError(
                f"Artikel '{artikelnr}' steht nicht im Katalog. Mit artikel_suchen nach der "
                f"richtigen Artikelnummer suchen oder beim Kunden nachfragen."
            )
        return KATALOG[artikelnr]

    # --- Berechnung (nur hier wird gerechnet!) ---------------------------

    def _kalkulieren(self, kunde: dict, positionen: list[dict]) -> dict:
        if not positionen:
            raise ToolError("Ein Angebot braucht mindestens eine Position.")
        nummern = [p["artikelnr"] for p in positionen]
        if len(nummern) != len(set(nummern)):
            raise ToolError("Jeder Artikel darf nur einmal vorkommen. Mengen bitte zusammenfassen.")

        zeilen, netto = [], Decimal("0")
        for i, p in enumerate(positionen, start=1):
            artikel = self._artikel(p["artikelnr"])
            menge = p["menge"]
            if not isinstance(menge, int) or isinstance(menge, bool) or menge <= 0:
                raise ToolError(f"Position {i}: Menge muss eine ganze Zahl größer 0 sein (erhalten: {menge}).")
            if menge > MAX_MENGE_PRO_POSITION:
                raise ToolError(f"Position {i}: Menge {menge} ist unplausibel hoch. Bitte beim Kunden bestätigen lassen.")

            if artikel["preis"] is None:
                raise ToolError(
                    f"Position {i}: Für Artikel {p['artikelnr']} ist kein Preis hinterlegt. "
                    f"Es wird kein Preis geschätzt oder erfunden. Bitte den Mitarbeiter fragen, "
                    f"welcher Preis gilt (er muss im Katalog gepflegt werden)."
                )
            staffel = next((r for ab, r in STAFFELRABATT if menge >= ab), Decimal("0"))
            rabatt = staffel + kunde["rabatt"]
            einzelpreis = geld(artikel["preis"] * (1 - rabatt))
            gesamt = geld(einzelpreis * menge)
            netto += gesamt
            zeilen.append({
                "pos": i, "artikelnr": p["artikelnr"], "bezeichnung": artikel["bezeichnung"],
                "einheit": artikel["einheit"], "menge": menge,
                "listenpreis": str(artikel["preis"]), "rabatt_prozent": str(rabatt * 100),
                "einzelpreis": str(einzelpreis), "gesamtpreis": str(gesamt),
            })
        mwst = geld(netto * MWST_SATZ)
        return {"positionen": zeilen, "netto": str(geld(netto)),
                "mwst": str(mwst), "brutto": str(geld(netto) + mwst)}

    # --- Dokumentkette ----------------------------------------------------

    def angebot_erstellen(self, kundennr: str, positionen: list[dict], bemerkung: str = "") -> dict:
        kunde = self._kunde(kundennr)
        kalkulation = self._kalkulieren(kunde, positionen)
        nr = self.store.naechste_nummer("AN")
        self.store.dokumente[nr] = {
            "nummer": nr, "typ": "Angebot", "status": "Entwurf", "kundennr": kundennr,
            "datum": self.store.heute.isoformat(),
            "gueltig_bis": (self.store.heute + timedelta(days=ANGEBOT_GUELTIG_TAGE)).isoformat(),
            "bezug": None, "bemerkung": bemerkung, **kalkulation,
        }
        return self._zusammenfassung(nr)

    def auftrag_bestaetigen(self, angebotsnr: str, bestellreferenz: str = "") -> dict:
        an = self._dokument(angebotsnr, "Angebot")
        if an.get("folgedokument"):
            raise ToolError(f"Zu {angebotsnr} gibt es bereits die Auftragsbestätigung {an['folgedokument']}.")
        if date.fromisoformat(an["gueltig_bis"]) < self.store.heute:
            raise ToolError(f"Angebot {angebotsnr} ist seit {an['gueltig_bis']} abgelaufen. Neues Angebot erstellen.")
        nr = self.store.naechste_nummer("AB")
        # Preise werden aus dem Angebot übernommen, nicht neu berechnet:
        # Der Kunde bekommt genau das, was ihm angeboten wurde.
        self.store.dokumente[nr] = {
            **copy.deepcopy({k: an[k] for k in ("kundennr", "positionen", "netto", "mwst", "brutto")}),
            "nummer": nr, "typ": "Auftragsbestätigung", "status": "Entwurf",
            "datum": self.store.heute.isoformat(), "bezug": angebotsnr,
            "bestellreferenz": bestellreferenz, "bemerkung": "",
        }
        an["status"] = "angenommen"
        an["folgedokument"] = nr
        return self._zusammenfassung(nr)

    def lieferschein_erstellen(self, auftragsnr: str) -> dict:
        ab = self._dokument(auftragsnr, "Auftragsbestätigung")
        if ab.get("folgedokument"):
            raise ToolError(f"Zu {auftragsnr} gibt es bereits den Lieferschein {ab['folgedokument']}.")
        fehlmengen = [
            f"{p['artikelnr']}: benötigt {p['menge']}, verfügbar {self.store.lager.get(p['artikelnr'], 0)}"
            for p in ab["positionen"] if self.store.lager.get(p["artikelnr"], 0) < p["menge"]
        ]
        if fehlmengen:
            raise ToolError("Lieferung nicht möglich, Lagerbestand reicht nicht: " + "; ".join(fehlmengen))
        for p in ab["positionen"]:
            self.store.lager[p["artikelnr"]] -= p["menge"]
        nr = self.store.naechste_nummer("LS")
        # Ein Lieferschein enthält bewusst keine Preise.
        self.store.dokumente[nr] = {
            "nummer": nr, "typ": "Lieferschein", "status": "Entwurf", "kundennr": ab["kundennr"],
            "datum": self.store.heute.isoformat(), "bezug": auftragsnr, "bemerkung": "",
            "positionen": [{k: p[k] for k in ("pos", "artikelnr", "bezeichnung", "einheit", "menge")}
                           for p in ab["positionen"]],
        }
        ab["status"] = "geliefert"
        ab["folgedokument"] = nr
        return self._zusammenfassung(nr)

    def dokument_anzeigen(self, dokumentnr: str) -> dict:
        return self._zusammenfassung(dokumentnr)

    def dokument_versenden(self, dokumentnr: str) -> dict:
        """Erzeugt das PDF und markiert das Dokument als versendet.
        Der Harness fragt VOR dem Aufruf einen Menschen um Freigabe."""
        dok = self._dokument(dokumentnr)
        if dok["status"] == "versendet":
            raise ToolError(f"{dokumentnr} wurde bereits versendet.")
        pfad = pdf_erzeugen(dok, self.store.kunden[dok["kundennr"]], self.pdf_ordner)
        dok["status"] = "versendet"
        dok["pdf"] = str(pfad)
        return {"dokumentnr": dokumentnr, "status": "versendet",
                "empfaenger": self.store.kunden[dok["kundennr"]]["email"], "pdf": str(pfad)}

    # --- Hilfen -----------------------------------------------------------

    def _dokument(self, nr: str, typ: str | None = None) -> dict:
        dok = self.store.dokumente.get(nr)
        if dok is None:
            raise ToolError(f"Dokument {nr} existiert nicht.")
        if typ and dok["typ"] != typ:
            raise ToolError(f"{nr} ist ein(e) {dok['typ']}, erwartet wird ein(e) {typ}.")
        return dok

    def _zusammenfassung(self, nr: str) -> dict:
        """Was das Modell zurückbekommt: fertig formatierte Beträge zum Vorlesen,
        damit es nichts selbst ausrechnen muss."""
        dok = self._dokument(nr)
        z = {"nummer": nr, "typ": dok["typ"], "status": dok["status"],
             "kunde": self.store.kunden[dok["kundennr"]]["name"], "datum": dok["datum"],
             "bezug": dok["bezug"], "folgedokument": dok.get("folgedokument")}
        if "gueltig_bis" in dok:
            z["gueltig_bis"] = dok["gueltig_bis"]
        z["positionen"] = [
            {"pos": p["pos"], "artikelnr": p["artikelnr"], "bezeichnung": p["bezeichnung"], "menge": p["menge"],
             **({"einzelpreis": fmt(Decimal(p["einzelpreis"])), "gesamtpreis": fmt(Decimal(p["gesamtpreis"])),
                 "rabatt": f"{Decimal(p['rabatt_prozent']).normalize():f} %"} if "einzelpreis" in p else {})}
            for p in dok["positionen"]
        ]
        if "netto" in dok:
            z["summen"] = {"netto": fmt(Decimal(dok["netto"])), "mwst_19": fmt(Decimal(dok["mwst"])),
                           "brutto": fmt(Decimal(dok["brutto"]))}
        return z


# ---------------------------------------------------------------------------
# PDF-Ausgabe
# ---------------------------------------------------------------------------

def pdf_erzeugen(dok: dict, kunde: dict, ordner: Path) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ordner.mkdir(parents=True, exist_ok=True)
    pfad = ordner / f"{dok['nummer']}.pdf"
    st = getSampleStyleSheet()
    klein = st["BodyText"].clone("klein", fontSize=8, leading=10)
    teile = [
        Paragraph(f"<b>{FIRMA['name']}</b> · {FIRMA['strasse']} · {FIRMA['ort']}", st["Normal"]),
        Spacer(1, 10 * mm),
        Paragraph(f"{kunde['name']}<br/>z. Hd. {kunde['ansprechpartner']}<br/>{kunde['strasse']}<br/>{kunde['ort']}", st["Normal"]),
        Spacer(1, 10 * mm),
        Paragraph(f"{dok['typ']} {dok['nummer']}", st["Title"]),
    ]
    kopf = [f"Datum: {dok['datum']}", f"Kundennr.: {dok['kundennr']}"]
    if dok.get("bezug"):
        kopf.append(f"Bezug: {dok['bezug']}")
    if dok.get("bestellreferenz"):
        kopf.append(f"Ihre Bestellung: {dok['bestellreferenz']}")
    if dok.get("gueltig_bis"):
        kopf.append(f"Gültig bis: {dok['gueltig_bis']}")
    teile += [Paragraph(" · ".join(kopf), st["Normal"]), Spacer(1, 6 * mm)]

    mit_preisen = "netto" in dok
    kopfzeile = ["Pos", "Art.-Nr.", "Bezeichnung", "Menge"] + (["Rabatt", "Einzelpreis", "Gesamt"] if mit_preisen else [])
    zeilen = [kopfzeile]
    for p in dok["positionen"]:
        z = [p["pos"], p["artikelnr"], Paragraph(p["bezeichnung"], klein), f"{p['menge']} {p['einheit']}"]
        if mit_preisen:
            z += [f"{Decimal(p['rabatt_prozent']).normalize():f} %", fmt(Decimal(p["einzelpreis"])), fmt(Decimal(p["gesamtpreis"]))]
        zeilen.append(z)
    if mit_preisen:
        for label, key in (("Summe netto", "netto"), ("zzgl. 19 % MwSt.", "mwst"), ("Gesamtbetrag", "brutto")):
            zeilen.append(["", "", "", "", "", label, fmt(Decimal(dok[key]))])
    breiten = [10 * mm, 25 * mm, 60 * mm, 22 * mm, 15 * mm, 25 * mm, 25 * mm] if mit_preisen else [12 * mm, 30 * mm, 100 * mm, 30 * mm]
    tabelle = Table(zeilen, colWidths=breiten, repeatRows=1)
    tabelle.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3b57")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, len(dok["positionen"])), 0.25, colors.grey),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
    ]))
    teile += [tabelle, Spacer(1, 8 * mm)]
    if dok.get("bemerkung"):
        teile.append(Paragraph(dok["bemerkung"], st["Normal"]))
    fuss = {
        "Angebot": "Wir freuen uns auf Ihren Auftrag. Zahlungsziel 14 Tage netto.",
        "Auftragsbestätigung": "Vielen Dank für Ihren Auftrag. Es gelten unsere AGB.",
        "Lieferschein": "Ware vollständig und unbeschädigt erhalten: ______________________ (Unterschrift)",
    }[dok["typ"]]
    teile.append(Paragraph(fuss, st["Normal"]))
    SimpleDocTemplate(str(pfad), pagesize=A4, title=f"{dok['typ']} {dok['nummer']}").build(teile)
    return pfad
