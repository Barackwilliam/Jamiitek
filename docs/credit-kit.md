# JamiiTek Credit Kit

Kipande cha kuweka kwenye **kila website tunayomtengenezea mteja**. Kinaonyesha
"Designed by JamiiTek" kwenye footer na kinaiambia Google kwamba JamiiTek ndiyo
iliyoitengeneza. Kila website mpya ni backlink mpya kwa jamiitek.com.

## Kanuni (soma kwanza)

1. **Ruhusa ya mteja.** Mweleze mteja na akubali. Credit ni sehemu ya mkataba, si siri.
2. **Link ionekane.** Isifichwe (hakuna `display:none`, rangi sawa na background, au font ndogo sana).
   Link iliyofichwa ni *link scheme* kwa Google na inaweza kuadhibu jamiitek.com na mteja.
3. **Jina tu kwenye link.** Tumia "JamiiTek". Usitumie maneno kama "best web design Tanzania"
   kwenye footer za wateja.
4. **HTML ya kawaida, si JavaScript.** Usiweke `<script src="jamiitek.com/...">` kwenye website ya mteja:
   Google inaipa link ya JavaScript uzito mdogo, na server yetu ikizima inaathiri wateja wote.
5. **Usiweke `rel="nofollow"`** kwenye credit (ruhusa ya mteja ipo, ni link halisi).
6. **Ongeza kazi kwenye portfolio.** Admin → Portfolio Items → mradi mpya, ukiwa na `live_url`,
   maelezo kamili na screenshot. Ukurasa wake (`/portfolio/<slug>/`) unarudisha link kwa mteja.

## 1. Credit kwenye footer (HTML)

Weka ndani ya mstari wa chini wa footer:

```html
<a class="jt-credit" href="https://www.jamiitek.com/" target="_blank" rel="noopener">
  Designed by <strong>JamiiTek</strong>
</a>
```

CSS ya msingi (badilisha rangi ziendane na footer ya mteja):

```css
.jt-credit { color: rgba(255, 255, 255, .6); font-size: .88rem; transition: color .2s; }
.jt-credit strong { color: #fff; font-weight: 800; }
.jt-credit:hover, .jt-credit:hover strong { color: #F5A623; }
```

## 2. Structured data (JSON-LD)

Ongeza `creator` kwenye `WebSite` schema ya mteja. Kama website haina schema bado, weka hii ndani ya `<head>`
(badilisha jina na URL ya mteja):

```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "WebSite",
  "name": "JINA LA MTEJA",
  "url": "https://www.example.co.tz/",
  "creator": {
    "@type": "Organization",
    "@id": "https://www.jamiitek.com/#organization",
    "name": "JamiiTek",
    "url": "https://www.jamiitek.com/"
  }
}
</script>
```

`@id` lazima ibaki `https://www.jamiitek.com/#organization`. Hiyo ndiyo inayounganisha websites zote za
wateja na Organization schema ya jamiitek.com.

## 3. Django (kama website ni Django)

`templates/partials/jamiitek_credit.html`:

```django
<a class="jt-credit" href="https://www.jamiitek.com/" target="_blank" rel="noopener">Designed by <strong>JamiiTek</strong></a>
```

Kwenye footer: `{% include "partials/jamiitek_credit.html" %}`

## 4. WordPress

Appearance → Theme File Editor → `footer.php` (au Customizer → Footer credit), weka HTML ya sehemu ya 1.
JSON-LD ya sehemu ya 2 iweke kupitia plugin ya "Insert Headers and Footers" → Header.

## 5. Baada ya kuzindua website ya mteja

- [ ] Credit inaonekana kwenye footer na inafungua www.jamiitek.com
- [ ] JSON-LD ina `creator` (jaribu kwenye https://search.google.com/test/rich-results)
- [ ] Mradi umeongezwa kwenye Portfolio ya jamiitek.com ukiwa na `live_url`
- [ ] Mteja ameombwa review kwenye Google Business Profile ya JamiiTek

Mfano halisi: WEMASA Tanzania. Credit iko kwenye footer ya https://www.wemasatanzania.org/ na case study
iko https://www.jamiitek.com/portfolio/wemasa-tanzania/.
