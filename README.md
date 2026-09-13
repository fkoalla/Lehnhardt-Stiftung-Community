# PORA Community — Blog der Lehnhardt-Stiftung

Ein Community-Blog für Teilnehmende der **PORA-Seminare** der
[Lehnhardt-Stiftung](https://lehnhardt-stiftung.org/): ein Ort für
Erfahrungsberichte, Praxistipps und offenen Austausch zwischen den Seminaren.

Technisch ist die Seite ein statischer **Jekyll**-Blog, der ohne eigenen Build-Server
direkt über **GitHub Pages** ausgeliefert werden kann.

## ⚠️ Wichtiger Hinweis zu Farben & Layout

Diese Version wurde **ohne direkten Zugriff auf lehnhardt-stiftung.org** erstellt —
der automatisierte Zugriff auf die Domain war in dieser Arbeitsumgebung durch die
Netzwerk-Policy blockiert, ein Abgleich der exakten Marken-Farbwerte, Schriften und
des Logos war daher nicht möglich.

Das aktuelle Theme (`assets/css/style.css`) orientiert sich an einem für die
Stiftung plausiblen Farbklima (gedecktes Petrol/Blau als Vertrauensfarbe, warmes
Terrakotta als Akzent, viel Weißraum) und ist bewusst über **CSS-Variablen** im
Kopf der Datei zentral steuerbar:

```css
:root {
  --color-primary: #14495c;
  --color-accent: #e08a4e;
  --color-bg: #faf7f1;
  /* … */
}
```

**Bitte vor dem Livegang die echten Werte von lehnhardt-stiftung.org übernehmen**
(Hex-Farben aus Logo/CSS, Schriftart, ggf. Logo-Datei in `assets/img/`) — die
Struktur des Themes muss dafür nicht verändert werden, nur diese Variablen.

## Struktur

```
_config.yml           Grundkonfiguration, Links zur Stiftung, giscus-Einstellungen
_layouts/              default (Grundgerüst), page (Infoseiten), post (Blogbeiträge)
_includes/             header, footer, post-card, comments (giscus)
_posts/                Blogbeiträge (Markdown mit Front Matter)
assets/css/style.css   Theme (Farben, Layout)
assets/js/main.js      Mobiles Menü
index.html             Startseite
blog.html              Blog-Übersicht (alle Beiträge)
pora-seminare.md       Info zu PORA
ueber-die-stiftung.md  Info zur Stiftung
austausch.md           Übersicht der Austausch-Kanäle
mitmachen.md           Anleitung zum Einreichen eigener Beiträge
```

## Lokal starten

```bash
bundle install
bundle exec jekyll serve
```

Die Seite ist danach unter `http://localhost:4000/Lehnhardt-Stiftung-Community/`
erreichbar (Pfad passend zu `baseurl` in `_config.yml`).

## Auf GitHub Pages veröffentlichen

1. Repository-Einstellungen → **Pages** → Quelle auf den Branch mit dieser Seite
   (z. B. `main`) und Root-Verzeichnis stellen.
2. `url` und `baseurl` in `_config.yml` an die tatsächliche GitHub-Pages-Adresse
   bzw. eine eigene Domain anpassen.
3. Optional: eigene Domain über eine `CNAME`-Datei im Repo-Root hinterlegen.

## Community-Austausch aktivieren (giscus)

Der Kommentarbereich unter jedem Blogbeitrag nutzt **[giscus](https://giscus.app/)**,
das GitHub Discussions als Kommentar-Backend nutzt — kostenlos, ohne eigenen Server,
moderierbar über GitHub.

1. Im Repository unter **Settings → General → Features** die Option
   **Discussions** aktivieren.
2. Eine Diskussions-Kategorie anlegen (z. B. `Austausch`, Format „Announcement“ oder
   „Open discussion“).
3. Die **giscus GitHub App** installieren: <https://github.com/apps/giscus>.
4. Auf <https://giscus.app/de> das Repository eintragen und die generierten Werte
   `data-repo-id` und `data-category-id` übernehmen.
5. Diese Werte in `_config.yml` unter `giscus.repo_id` und `giscus.category_id`
   eintragen. Der Kommentarbereich erscheint danach automatisch auf jedem Beitrag.

Bis dahin verweist die Seite [`austausch.html`](austausch.html) auf die
GitHub-Discussions-Übersicht als zentralen Anlaufpunkt für offene Themen.

## Neuen Blogbeitrag hinzufügen

Neue Datei unter `_posts/` anlegen, Dateiname im Format
`YYYY-MM-DD-kurzer-titel.md`, z. B.:

```markdown
---
title: "Mein Titel"
category: "Erfahrungsbericht"
author: "Vorname / Kürzel"
excerpt: "Ein Satz, der im Blog-Überblick als Teaser erscheint."
---

Text des Beitrags in Markdown …
```

Details und Einreichungsprozess für Community-Mitglieder stehen auf der Seite
[„Mitmachen“](mitmachen.md).

## Moderation & Ton

Der Blog ist ein von Teilnehmenden getragenes Angebot der PORA-Community und ersetzt
keine medizinische, therapeutische oder pädagogische Beratung. Hinweise dazu stehen
auf den Seiten „Über die Stiftung“ und „Austausch“.
