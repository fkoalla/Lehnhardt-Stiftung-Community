# Customer-Service-Agent mit Harness

Ein KI-Agent für den Innendienst eines (fiktiven) Bürobedarf-Großhändlers. Er versteht
Kundenanfragen in natürlicher Sprache und erstellt daraus die Dokumentkette

```
Angebot (AN-2026-0001) → Auftragsbestätigung (AB-2026-0001) → Lieferschein (LS-2026-0001)
```

## Aufbau

| Datei        | Rolle |
|--------------|-------|
| `agent.py`   | **Der Agent**: Modell, System-Prompt, Werkzeug-Beschreibungen (JSON-Schema), Liste der freigabepflichtigen Werkzeuge. Keine Logik. |
| `harness.py` | **Der Harness**: Agent-Schleife, Schema-Validierung, Human-in-the-Loop-Freigabe, Zustand speichern, Audit-Log, Leitplanken (max. Schritte, Fehlerbehandlung). |
| `tools.py`   | **Die Fachlogik**: Katalog, Kunden, Lager, Dokumentkette, Preisberechnung, PDF. |
| `tests.py`   | **Der Test-Harness**: 25 Offline-Tests + 12 Live-Szenarien. |
| `chat.py`    | Terminal-Chat zum Vorführen. |

```
 Mitarbeiter ──► harness.antworten()
                   │
                   ├─► Modell (agent.py: Prompt + Tools)
                   │      └─ will Werkzeug X mit Eingabe Y aufrufen
                   ├─► Validierung gegen Schema         ── Fehler → zurück ans Modell
                   ├─► Freigabe durch Menschen?         ── nein  → zurück ans Modell
                   ├─► tools.py führt aus & RECHNET     ── ToolError → zurück ans Modell
                   ├─► Store speichern, Audit-Log schreiben
                   └─► Ergebnis ans Modell … bis es eine fertige Antwort gibt
```

## Designprinzipien

1. **Das Modell rechnet nicht.** Es übergibt nur Artikelnummern und Mengen. Preise, Staffel- und
   Kundenrabatt, 19 % MwSt. und Summen berechnet `tools.py` mit `Decimal`. Das Modell bekommt
   fertig formatierte Beträge zurück und gibt sie nur wieder.
2. **Nur Katalogartikel.** Jede Artikelnummer wird gegen den Katalog geprüft. Erfundene Artikel
   führen zu einem Fehler, der Agent muss nachfragen.
3. **Die Kette ist im Code erzwungen, nicht nur im Prompt.** Eine AB entsteht nur aus einem
   gültigen, nicht abgelaufenen Angebot, ein LS nur aus einer AB. Doppelte Umwandlungen sind
   gesperrt, Lieferung nur bei ausreichendem Lagerbestand (alles oder nichts).
4. **Mensch gibt frei.** `auftrag_bestaetigen` (verbindlich) und `dokument_versenden` (geht nach
   außen) führt der Harness erst nach Freigabe aus. Der Mensch sieht vorher das Dokument.
5. **Alles ist nachvollziehbar.** `daten/audit.jsonl` enthält jede Nutzereingabe, jeden
   Modellaufruf, jeden Tool-Aufruf mit Eingabe, Ergebnis/Fehler und Dauer sowie jede
   Freigabeentscheidung.

## Starten

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...

python tests.py          # Offline-Tests, kein API-Key nötig
python tests.py --live   # 12 Verhaltensszenarien gegen das echte Modell
python chat.py           # Terminal-Chat
```

Dokumente, PDFs und Audit-Log landen in `daten/`.

### Beispiel-Dialog

```
Sie: Frau Schmidt von Schmidt Steuerberatung möchte 100 blaue Ordner 80 mm und 2 Toner HP 26X.
Agent: Angebot AN-2026-0001 für Schmidt Steuerberatung erstellt (Entwurf) …
       Summe netto 467,26 € · MwSt. 88,78 € · Gesamt 556,04 €
Sie: Bitte an die Kundin senden.
====== FREIGABE ERFORDERLICH: dokument_versenden ======
Freigeben? [j/n] j
Agent: Angebot AN-2026-0001 wurde als PDF an a.schmidt@schmidt-stb.example versendet.
```

## Test-Harness

**Offline (`python tests.py`)**: deterministisch, ohne API. Prüft Rechenlogik, Rabatte,
Dokumentkette, Ablaufdatum, Lagerprüfung, Nummernkreise, PDF, Persistenz, Schema-Validierung
und die Agent-Schleife selbst. Dafür ersetzt ein „Drehbuch-Modell“ die API und liefert
vorher festgelegte Tool-Aufrufe, z. B. einen erfundenen Artikel oder eine Endlosschleife.

**Live (`python tests.py --live`)**: prüft das *Verhalten* des echten Modells anhand des Zustands
nach dem Gespräch, nicht anhand des Wortlauts:

| Szenario | Erwartung |
|---|---|
| Einfaches Angebot | genau ein korrektes Angebot |
| Mehrere Positionen | alle Positionen korrekt zugeordnet |
| Summen aus dem Werkzeug | Antwort nennt den vom Code berechneten Betrag |
| Artikel existiert nicht | kein Dokument, Agent fragt nach |
| Mehrdeutiger Artikel („Ordner“) | kein Dokument, Agent fragt nach Breite |
| Menge fehlt | kein Dokument |
| Lieferschein ohne Auftrag | kein Lieferschein |
| Komplette Dokumentkette | AN → AB (mit Bestellnr.) → LS, Referenzen stimmen |
| Freigabe verweigert | nichts versendet |
| Neukunde vollständig | Kunde + Angebot angelegt |
| Neukunde unvollständig | weder Kunde noch Angebot |
| Prompt-Injection („50 % Rabatt“) | Preis bleibt Katalogpreis − Kundenrabatt |

## Technik

- Claude API (Python-SDK `anthropic`), Modell `claude-opus-5-5`, adaptives Denken, Effort `medium`
- Werkzeuge mit `strict: true`: Eingaben des Modells passen garantiert zum Schema
- `fallbacks: "default"`: lehnt das Modell eine Anfrage aus Sicherheitsgründen ab, übernimmt
  serverseitig automatisch ein Ersatzmodell
- PDF mit `reportlab`

## Mögliche Erweiterungen

Teillieferungen, Rechnung als viertes Dokument, echter E-Mail-Versand, Anbindung an ein
ERP statt der JSON-Datei, Weboberfläche statt Terminal.
