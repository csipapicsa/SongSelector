# Traktor Key Calculator – projektáttekintés és verziótérkép

Dokumentum dátuma: 2026-10-27.  
A rekonstruált munka időszaka: 2026-10-13–14.  
Forrás: a „Find the Python music app” című korábbi beszélgetés.  
Beszélgetésazonosító: 01a1365b-c1d7-7860-b87a-eb8db1387904.

> Ez történeti rekonstrukció a korábbi beszélgetés elérhető üzeneteiből.
> Az első összeállításkor a helyi parancsfuttatás nem működött, ezért a
> projektfájlokat nem sikerült újra leltározni, összehasonlítani vagy tesztelni.
> A mostani mentés ezt a rekonstrukciót helyezi el a SongSelector projektben;
> nem jelent új, teljes fájlauditot vagy új tesztfuttatást.
> Az ismeretlen fájlneveket és útvonalakat külön jelöljük.

## 1. Mi ez az alkalmazás?

Pythonban készült DJ-segédprogram. A zenék eredeti BPM-je és hangneme
alapján megjeleníti, hogyan változna a hangnem más lejátszási tempónál.

A régebbi változatok CSV-ből töltötték a zeneadatokat. Az újabbakban
fájlmetaadat-kezelés, könyvtár- és playlistfelület, majd Traktor-adatokkal
történő kiegészítés is szerepelt.

A 2026. októberi munka fő részei:

- A régi alkalmazás és forrásverziók megkeresése.
- A v1–v4 változatokból futtatható exe-k készítése.
- Külön fejlesztési másolat létrehozása a stabil v4 alapján.
- MP3-fájlok drag-and-drop importjának javítása.
- Hiányzó metaadatok kiegészítése a Traktor gyűjteményéből.
- Színek, keresés és rating megjelenítésének javítása.
- Automatizált és csomagolt alkalmazáson végzett ellenőrzések.
- Külön vizsgálat egy új oszlop lehetőségéről a Traktor saját böngészőjében.

Az elérhető előzmény nem igazolja, hogy ekkor új, hangjelből dolgozó
automatikus BPM- vagy hangnemfelismerőt készítettünk volna. A munka
meglévő metaadatok és Traktor-adatok beolvasására épült.

A tempó alapján történő hangnemváltozás értelmezése a későbbi Traktor-tervben
kikapcsolt Key Lock mellett szerepelt. A kód pontos képletét, kerekítését és
jelöléskonverzióit ebben a rekonstrukcióban nem sikerült újra ellenőrizni.

## 2. A legfontosabb mappák

### 2.1. Régi safety projekt: korai források és egy régi exe

~~~text
E:\GITHUB_E\_Master Thesis Safet\development_app
~~~

Ez egy régebbi projektmásolat. Itt találtunk:

- VERSION 1 almappát.
- VERSION 2 almappát.
- VERSION 3 almappát.
- Több „good” nevű Python-változatot.
- Egy régi, már elkészült exe-t.

A Python-fájlok teljes neve és listája az elérhető előzményből nem
állapítható meg.

A régi exe:

~~~text
E:\GITHUB_E\_Master Thesis Safet\development_app\dist\TraktorKeyCalculator.exe
~~~

A kereséskor körülbelül 35 MB-os volt, a jelentett módosítási dátuma
2025-04-04. Ez fájldátum, nem bizonyított fordítási dátum.

### 2.2. Újabb eredeti fejlesztési gyűjtemény

~~~text
E:\GITHUB_E\MasterThesis\development_app
~~~

Ebben újabb Python-források és több version4_... nevű mappa volt.

Az újrafordításhoz kiválasztott stabil alap:

~~~text
E:\GITHUB_E\MasterThesis\development_app\version4_20251104
~~~

A kiválasztás oka:

- Az info.txt fájlban „Stabil version.” megjegyzés szerepelt.
- A források 2025. novemberi módosításokat tartalmaztak.
- Ez volt a keresés során azonosított legerősebb újabb forrásjelölt.

A korábbi beszámoló szerint MP3/WAV/FLAC metaadatokból olvasta a BPM-et
és a hangnemet.

A többi version4_... mappa pontos neve, eltérése és egymáshoz való
viszonya jelenleg nincs teljesen feltérképezve.

### 2.3. A v1–v4 újrafordításának területe

~~~text
E:\APP\TraktorKeyCalculator_rebuilt_20261013
~~~

Az elkészült exe-k:

~~~text
E:\APP\TraktorKeyCalculator_rebuilt_20261013\release
~~~

Ez a történeti generációk újrafordítására létrehozott terület.

A buildhez másolt források, pótolt adatok, környezetek és segédszkriptek
pontos belső útvonalai nem szerepelnek az elérhető üzenetekben.
Nem ellenőrzött, hogy itt source vagy tests nevű almappák vannak-e.

### 2.4. A továbbfejlesztett alkalmazás külön forrásmásolata

~~~text
E:\APP\TraktorKeyCalculator_codex_20261013\source
~~~

Ez a legutolsó dokumentált továbbfejlesztési munkapéldány.

Itt készült:

- Drag-and-drop javítás.
- Traktor-metaadatokkal történő kiegészítés.
- Színkezelési javítások.
- Keresés bővítése.
- Rating megjelenítése és keresése.
- Színneves keresés és Colors választó.

A fejlesztés a stabil v4 vonalából indult.

Az ebből készült exe-k:

~~~text
E:\APP\TraktorKeyCalculator_codex_20261013\release
~~~

Az előzmények egy közös, tovább módosított source mappát neveznek meg.
Nem bizonyított, hogy minden kiadott exe mellé külön, változatlan
forráspillanatkép vagy Git-tag is készült.

### 2.5. Külső Traktor-adatforrás

~~~text
E:\DJ\TRAKTOR\collection.nml
~~~

Ez a Traktor gyűjteményadata, nem a saját alkalmazás forráskódja.

A fejlesztett alkalmazás innen egészített ki hiányzó metaadatokat.
Az eredeti utasítás szerint ezt és a zenefájlokat változatlanul kellett
megőrizni. A korábbi beszámolók ezt ellenőrzöttnek jelentették.

### 2.6. Külön Traktor-módosítási vizsgálat

~~~text
E:\APP\TraktorBrowserColumnLab\Installation
E:\APP\TraktorBrowserColumnLab\README.txt
~~~

Ez egy külön vizsgálati irány volt: új, számított hangnemet mutató oszlop
a Traktor saját böngészőjében.

Nem a Python-app következő elkészült verziója.

## 3. A változatok kapcsolata

~~~text
Korai eredeti Python-változatok:
VERSION 1 / VERSION 2 / VERSION 3
  └─ külön helyreállított buildmásolatok
       └─ rebuilt_20261013\release
            ├─ TraktorKeyCalculator_v1.exe
            ├─ TraktorKeyCalculator_v2.exe
            └─ TraktorKeyCalculator_v3.exe

MasterThesis\development_app\version4_20251104
  ├─ külön újrafordítás
  │    └─ rebuilt_20261013\release\TraktorKeyCalculator.exe
  └─ külön fejlesztési másolat
       └─ codex_20261013\source
            ├─ DragDrop
            ├─ DragDrop_Colors
            ├─ DragDrop_Colors_Search
            ├─ DragDrop_Colors_Search_Ratings
            └─ ColorSearch_Ratings

Külön irány:
Traktor Pro 3.8.0.46 telepítésmásolat
  └─ TraktorBrowserColumnLab
       └─ böngészőoszlop lehetőségének vizsgálata
~~~

A v1–v3 pontos bemeneti projektpéldánya és fájlonkénti eredete nem
rekonstruálható teljes bizonyossággal az elérhető üzenetekből.

A korai mappák a safety projektben biztosan szerepeltek, de ebből még
nem következik, hogy minden build minden fájlját közvetlenül onnan
másoltuk.

A „v4” az eredeti generáció megnevezése. A későbbi hosszú exe-nevek
ennek továbbfejlesztései.

## 4. Az exe-k teljes dokumentált listája

### 4.1. Régi, már létező exe

~~~text
E:\GITHUB_E\_Master Thesis Safet\development_app\dist\TraktorKeyCalculator.exe
~~~

Ez a keresés során előkerült történeti példány. Nem az október 13-án
újrafordított v4 és nem a későbbi javításokat tartalmazó kiadás.

### 4.2. Újrafordított v1

~~~text
E:\APP\TraktorKeyCalculator_rebuilt_20261013\release\TraktorKeyCalculator_v1.exe
~~~

- Korai Tkinter-változat.
- Régebbi CSV-formátumot várt.
- Külön buildkörnyezet készült hozzá.
- A jelentett ellenőrzésben 1190 zeneadatot töltött be.
- Ellenőriztük a tempófüggő hangnemfrissítést és az indulást.

### 4.3. Újrafordított v2

~~~text
E:\APP\TraktorKeyCalculator_rebuilt_20261013\release\TraktorKeyCalculator_v2.exe
~~~

- Korábbi második változat.
- Régebbi CSV-formátumot várt.
- A jelentett ellenőrzésben 1190 zeneadatot töltött be.
- Ellenőriztük a tempófüggő hangnemfrissítést és az indulást.

### 4.4. Újrafordított v3

~~~text
E:\APP\TraktorKeyCalculator_rebuilt_20261013\release\TraktorKeyCalculator_v3.exe
~~~

- Playlistes harmadik változat.
- A hiányzó functions.py modult pótolni kellett a buildmásolatban.
- A jelentett ellenőrzésben 2920 zeneadatot töltött be.
- Ellenőriztük a tempófüggő hangnemfrissítést és az indulást.

### 4.5. Újrafordított stabil v4

~~~text
E:\APP\TraktorKeyCalculator_rebuilt_20261013\release\TraktorKeyCalculator.exe
~~~

- Alapja a version4_20251104.
- A zeneadatokat is becsomagoltuk.
- A jelentett ellenőrzésben 2920 zeneadatot töltött be.
- Ez lett a későbbi továbbfejlesztések alapja.

A fájlnévben nincs „v4” utótag. Emiatt könnyen összekeverhető a safety
másolat ugyanolyan nevű régi exe-jével.

A korábbi beszámoló szerint mind a négy újrafordított exe Python
telepítése nélkül futtatható volt. A normál Windows-indítás során
ablakot hoztak létre, válaszoltak és rendesen bezárultak.

### 4.6. Drag-and-drop javítás

~~~text
E:\APP\TraktorKeyCalculator_codex_20261013\release\TraktorKeyCalculator_DragDrop.exe
~~~

Új tartalom:

- Tényleges import könyvtárba és playlistbe.
- MP3-metaadatok beolvasása.
- Traktor-adatok használata hiányzó értékekhez.
- Több hangnemjelölés támogatása.
- Duplikátumok kezelése.
- Importok megőrzése újraindítás után.

Jelentett ellenőrzés: 10 automatizált teszt, csomagolt alkalmazáspróbák
és Windows-indítás. Az exe ekkor körülbelül 59 MB-os volt.

### 4.7. Színkezelési javítás

~~~text
E:\APP\TraktorKeyCalculator_codex_20261013\release\TraktorKeyCalculator_DragDrop_Colors.exe
~~~

Új tartalom:

- Színek mindkét panelen.
- Color by Key működésének javítása.
- Playlist színoszlopának láthatóvá tétele.
- Traktor-kategóriaszín és hangnem szerinti színezés.
- Meglévő részletek megőrzése hiányzó tagek esetén.

Jelentett ellenőrzés: 17 automatizált teszt és exe-indítási próbák.

### 4.8. Keresési összehasonlítások

~~~text
E:\APP\TraktorKeyCalculator_codex_20261013\release\TraktorKeyCalculator_DragDrop_Colors_Search.exe
~~~

Új tartalom:

- Nagyobb mint.
- Kisebb mint.
- Legalább.
- Legfeljebb.
- Tizedes számok kezelése.

A korábbi beszámoló BPM, rating és szín mezőket említett.

Jelentett ellenőrzés: 23 automatizált teszt és exe-próbák.

### 4.9. Rating megjelenítése és keresése

~~~text
E:\APP\TraktorKeyCalculator_codex_20261013\release\TraktorKeyCalculator_DragDrop_Colors_Search_Ratings.exe
~~~

Új tartalom:

- Rating láthatóvá tétele mindkét panelen.
- Rating kereshetősége.
- Hiányzó ratingek pótlása Traktor-adatokból.
- Például Rating ≥ 4 feltétel.

A korábbi beszámoló szerint 1954 meglévő zenénél pótoltuk a ratinget.

Jelentett ellenőrzés: 30 automatizált teszt és exe-próbák.

### 4.10. Színneves keresés és Colors választó

~~~text
E:\APP\TraktorKeyCalculator_codex_20261013\release\TraktorKeyCalculator_ColorSearch_Ratings.exe
~~~

Új tartalom:

- Színnevek használata a keresősávban.
- Colors lenyíló választó.
- Több szín kijelölése.
- Színek kizárása.
- Szín nélküli tételek keresése.
- A választó és a begépelt feltételek szinkronja.

Jelentett ellenőrzés: 40 automatizált teszt, csomagolt alkalmazáspróbák
és Windows-indítás.

**Ez a legutolsó dokumentált kész exe.**

A fejlesztések egymásra épültek. A végső fájlnévből kimaradt DragDrop
és Search szó nem jelenti e funkciók eltávolítását.

A jelenlegi fájltartalmát és azóta történt esetleges felülírását a
dokumentum összeállításakor nem sikerült ellenőrizni.

## 5. Mi történt a forrásokkal és az újrafordítással?

### 5.1. Kezdetben csak kerestünk

Az eredeti kérés az alkalmazás megtalálása volt, módosítás és törlés
nélkül.

Előkerült:

- A safety másolat régi exe-je.
- Az újabb MasterThesis-forrásgyűjtemény.
- Több eredeti fejlesztési generáció.
- A stabilnak jelölt version4_20251104.

A korábbi keresésben 1539 exe-t és 508 ZIP tartalomjegyzékét ellenőriztük.
Ezek között nem került elő újabb kész példány.

### 5.2. Miért nem volt exe az újabb projektben?

A korábbi Git-vizsgálat szerint:

- A MasterThesis projektben 2025-10-30-i buildnyomok voltak.
- A hozzájuk tartozó célútvonalakon a kereséskor nem volt exe.
- Egy 2025-11-02-i commit eltávolította a dist\TraktorKeyCalculator.exe
  fájlt a verziókövetésből.
- A .gitignore kizárta az exe-ket.
- A Gitben megőrzött korábbi exe bájtra azonos volt a safety exe-vel.

A verziókövetésből kivétel önmagában nem bizonyítja, mikor vagy miért
tűnt el egy fájl a helyi lemezről.

Az biztosnak jelentett állapot az volt, hogy a kereséskor az újabb
projekt dist mappájában nem volt kész exe.

A commit pontos azonosítója és az összehasonlított hashértékek nincsenek
benne az elérhető beszélgetésrészletekben.

### 5.3. V4 újrafordítása

A version4_20251104 lett az alap. Külön buildterület készült, az eredeti
források megtartásával.

A korábbi forrásellenőrzés:

- 2920 zeneadatot töltött be.
- A felületen frissült a hangnem tempóváltásra.
- A példatesztben C-dúr 100 BPM-ről 150 BPM-re állítva G-dúrra változott.

Ez jelentett működési próba, nem teljes zeneelméleti validáció.

Az elkészült exe-t külön is ellenőriztük.

### 5.4. V1–v3 helyreállítása

A régi változatok nem voltak minden szempontból hiánytalanok.

V1 és V2:

- Korábbi formátumú CSV-t vártak.
- A szükséges adatokat meglévő projektpéldányokból pótoltuk.
- A pótlás a külön buildmásolatokban történt.

V3:

- Hiányzott a functions.py.
- Ezt meglévő projektpéldányból pótoltuk a buildmásolatban.

V1:

- Tkintert használt.
- Külön buildkörnyezet készült hozzá.

A pótolt CSV-k pontos neve és forrásútvonala, valamint a functions.py
donorának teljes útvonala nem szerepel az elérhető üzenetekben.
Ezek a reprodukálhatóság fontos hiányzó részletei.

## 6. Mi változott a Codex-forrásmásolatban?

A felhasználói kérés kifejezetten külön fejlesztési másolatot
engedélyezett. Az eredeti fejlesztési fájlokat meg kellett őrizni,
a másolatban lehetett javítani.

A dokumentált munkapéldány:

~~~text
E:\APP\TraktorKeyCalculator_codex_20261013\source
~~~

### 6.1. Drag-and-drop

A feltárt hiba szerint a meglévő drop handler olvasott metaadatokat,
de nem hozott létre új sort a felületen.

A javítás után a dobott fájlok bekerültek a könyvtárba vagy playlistbe.

Tesztelt viselkedések:

- Több fájl dobása.
- Duplikált fájlok kezelése.
- Hiányzó metaadatok.
- Traktor-adatokkal történő kiegészítés.
- Újraindítás után az importok visszatöltése.
- Importált playlisttételek hangnemfrissítése tempóváltásra.

Az importokat tároló fájl/adatbázis neve és helye nem szerepel az
elérhető előzményben.

### 6.2. Hangnemjelölések és Traktor-metaadatok

Valós MP3-fájlokban zenei hangnemnév és Traktor Open Key jelölés is
előkerült, például Bm és 3m.

A jelentett támogatás:

- Zenei hangnemnevek.
- Camelot.
- Traktor Open Key.

A hiányzó adatokhoz a következő collection lett adatforrás:

~~~text
E:\DJ\TRAKTOR\collection.nml
~~~

A teljes mezőprioritást és a pontos illesztési algoritmust a kódból
kell ellenőrizni.

### 6.3. Színek

Két konkrét hiba került elő:

1. A Color by Key beállítás nem befolyásolta a sorok színét.
2. A playlist színoszlopa rejtve volt.

Mindkettőt javítottuk.

A Settings → Coloring Options… alatt választható lett:

- Traktor-kategóriaszín.
- Hangnem szerinti színezés.

Mindkét panel megkapta a megfelelő megjelenítést.

Adatfrissítéskor megőriztük a meglévő részleteket, ha hiányoztak a tagek.
A Traktor kifejezett „nincs szín” értéke viszont törölhette a régi színt.

### 6.4. Complex Search

Numerikus összehasonlításokat adtunk hozzá.

Példa két feltételre:

~~~text
Original BPM > 120
Original BPM < 130
~~~

Tizedes értékek is használhatók lettek.

A színmező numerikus rendezésének pontos jelentését és a teljes
keresési nyelvtant a kódból kell ellenőrizni.

### 6.5. Rating

A rating mező már létezett, de:

- Régebbi beállítások elrejtették.
- A becsomagolt zenelistában nem voltak ratingértékek.

A javítás:

- Láthatóvá tette az 1–5 értékeket mindkét panelen.
- Kereshetővé tette őket.
- A hiányzó értékeket kiegészítette a Traktor collectionből.
- Megőrizte a fájlokból már beolvasott ratingeket.

A korábbi beszámoló szerint 1954 meglévő zenénél történt kiegészítés.

Ez az app adataira vonatkozó kiegészítésként szerepelt. A Traktor
collection átírását nem jelentettük.

### 6.6. Színkeresés

Példák:

~~~text
color:blue
color:red,orange
tribal color:blue
-color:blue
color:none
~~~

A kereső mellé Colors választó került, több szín kijelölésével.

A választó és a begépelt feltételek szinkronban maradtak. A színfilter
akkor is működött, ha a Color nem volt kijelölve a Search Columns alatt.

A színnevek a Complex Search felületen is használhatók lettek.

Ezek a feltételek a Traktor színjelöléseire vonatkoztak.
A hangnem szerinti megjelenítési színezést ettől külön kell értelmezni.

## 7. Tesztek és ellenőrzések

### 7.1. Hol vannak a tesztfájlok?

**A tesztfájlok pontos nevét és helyét az elérhető előzményekből nem
sikerült megállapítani.**

A beszélgetés rögzíti az eredményeket és az ellenőrzött viselkedéseket,
de nem tartalmaz teljes fájllistát vagy futtatási útmutatót.

Keresési célpontok:

~~~text
E:\APP\TraktorKeyCalculator_codex_20261013
E:\APP\TraktorKeyCalculator_rebuilt_20261013
~~~

Ezek keresési célpontok, nem bizonyított tests könyvtárak.

### 7.2. Mit ellenőriztünk?

| Szakasz | Korábban jelentett ellenőrzés |
|---|---|
| V4 újrafordítás | 2920 adat, forrás- és exe-próba, tempóra változó hangnem |
| V1–v3 újrafordítás | 1190/1190/2920 adat, felületi hangnemfrissítés |
| Mind a négy rebuilt exe | Normál Windows-indítás, válaszoló ablak, rendes bezárás |
| DragDrop | 10 teszt: Qt drop események, valós MP3, Open Key, fallback, duplikátum, újraindítás |
| Colors | 17 teszt: Traktor-szín, mindkét panel, tempófüggő színek, festett színpontok pixelei |
| Search | 23 teszt: keresési feltételek és korábbi funkciók |
| Ratings | 30 teszt: láthatóság, keresés, fallback, korábbi funkciók |
| ColorSearch | 40 teszt: színnevek, választó, szinkron, BPM/rating kombinációk |

A 10/17/23/30/40 számok az egyes lépésekben jelentett tesztkészletméretek.
Nem szabad ezeket összeadni és független tesztekként értelmezni.

A fejlesztett exe-knél külön csomagolt alkalmazáspróbákról és normál
Windows-indítási ellenőrzésekről is beszámoltunk.

### 7.3. Mi hiányzik a tesztek dokumentációjából?

- Tesztfájlok pontos neve és útvonala.
- Tesztkeretrendszer.
- Futtatóparancsok.
- Tesztadatok és naplók helye.
- A használt Python- és csomagverziók.
- Annak ellenőrzése, hogy minden tesztfájl megmaradt-e a lemezen.

A korábbi sikeres futások nem jelentik, hogy most újra lefuttattuk őket.

## 8. Fájlszintű változásjegyzék

Az alábbi lista a bizonyítható részletességig megy el.

| Fájl vagy fájlcsoport | Mi történt vele? | Mi hiányzik? |
|---|---|---|
| Eredeti MasterThesis és safety források | Megkerestük és olvastuk; a build/javítás külön másolatokon készült | Aktuális eltérésvizsgálat |
| version4_20251104\info.txt | A stabil alap kiválasztását indokolta | Teljes tartalom és jelenlegi állapot |
| V1/V2 CSV-k | Régi formátumhoz szükséges adatokat pótoltunk a buildmásolatokban | Fájlnevek és donorútvonalak |
| V3 functions.py | Hiányzó modult pótoltunk a buildmásolatban | Pontos donor- és célútvonal |
| Codex source Python-fájljai | Drop, metaadat, szín, keresés és rating javításai | Modulonkénti lista és diff |
| Rebuilt release exe-k | Négy történeti generációt fordítottunk újra | Hash, buildrecept, forráspillanatkép |
| Codex release exe-k | Öt egymásra épülő funkciókiadás készült | Hash és kiadásonkénti forráspillanatkép |
| App importált adatai és beállításai | Importmegőrzés, láthatóság, fallback-adatok | Tárolófájlok neve és helye |
| collection.nml és zenefájlok | Adatforrásként használtuk; változatlannak jelentettük | Jelenlegi ellenőrzés |
| TraktorBrowserColumnLab\README.txt | Integrációs vizsgálat jegyzetei kerültek bele | Jelenlegi tartalomellenőrzés |

A modulnevek hiányában nem lenne megalapozott például main.py,
metadata.py vagy test_dragdrop.py neveket kitalálni és tényleges
projektfájlként felsorolni.

## 9. Külön vizsgálat: új oszlop a Traktorban

2026-10-14-én felmerült egy „Key at Master BPM” oszlop a Traktor saját
böngészőjében.

A cél az lett volna, hogy a böngésző minden zenénél mutassa az aktuális
master tempóhoz tartozó új hangnemet, kikapcsolt Key Lock mellett.

A korábbi beszámoló szerint teljes másolat készült a Traktor Pro
3.8.0.46 telepítéséről:

~~~text
E:\APP\TraktorBrowserColumnLab\Installation
~~~

A vizsgálat eredménye:

~~~text
E:\APP\TraktorBrowserColumnLab\README.txt
~~~

Az akkori megállapítás:

- Az asztali zenelista natív, fordított vezérlő.
- Az elérhető QML-fájlok a kontrollerképernyőkhöz tartoztak.
- A telepítésmásolat önmagában nem választotta volna le a Traktor
  collectionjét és beállításait.
- További vizsgálathoz külön Windows-tesztkörnyezet merült fel.

**Az extra oszlop nem készült el.**

A Python-app élő master BPM-követése is lehetőségként szerepelt,
de az elérhető előzmény nem dokumentál kész integrációt.

Javasolt VM-hely:

~~~text
E:\APP\TraktorBrowserColumnLab\VM
~~~

Ez tervként szerepelt. A VM sikeres létrehozása és használata nincs
igazolva, ezért nem kezelhető elkészült projektkomponensként.

## 10. Miért nehéz most átlátni a projektet?

1. Több eredeti projektmásolat őrzi az előzményeket.
2. Dátumos mappák, VERSION mappák és „good” nevű változatok keverednek.
3. Ugyanaz az exe-fájlnév különböző korszakokat jelöl.
4. Régi buildnyomok mellett nem feltétlenül maradt meg a kész exe.
5. A régi verziók helyreállításához más példányokból kellett fájlokat
   és adatokat pótolni.
6. A továbbfejlesztések funkcióneves exe-kként jelentek meg.
7. Egy közös source mappa fejlődött tovább; kiadásonkénti változatlan
   forrásmentések léte nincs igazolva.
8. Az alkalmazás külső Traktor-adatforrásra is támaszkodik.
9. Régi felhasználói beállítások elrejthettek fontos oszlopokat.
10. A teszteredmények megvannak a beszélgetésben, de a lemezen lévő
    tesztek és buildsegédek teljes térképe hiányzik.

2026-10-13-án 21:57-kor a felhasználó kérte, hogy a továbbiakban a
fejlesztett aktuális példányt tartsuk karban újabb változatmásolatok
készítése nélkül. Ezt elfogadtuk.

Ez karbantartási megállapodás volt; önmagában nem dokumentál további
buildet vagy fájlmódosítást.

## 11. Honnan érdemes folytatni?

### Továbbfejlesztés legutolsó dokumentált forrása

~~~text
E:\APP\TraktorKeyCalculator_codex_20261013\source
~~~

### Legutolsó dokumentált kész kiadás

~~~text
E:\APP\TraktorKeyCalculator_codex_20261013\release\TraktorKeyCalculator_ColorSearch_Ratings.exe
~~~

### Eredeti stabil alap összehasonlításhoz

~~~text
E:\GITHUB_E\MasterThesis\development_app\version4_20251104
~~~

### Régi generációk újrafordított exe-i

~~~text
E:\APP\TraktorKeyCalculator_rebuilt_20261013\release
~~~

### Régi safety példány

~~~text
E:\GITHUB_E\_Master Thesis Safet\development_app
~~~

A dokumentum elhelyezése a SongSelector projektben önmagában nem jelenti,
hogy az alkalmazás fenti forrásait vagy exe-it is átmásoltuk ide.

## 12. A teljes fájlaudithoz még pótolandó

- Minden releváns mappa teljes fájllistája.
- Az eredeti Python-változatok belépési pontja és függőségei.
- A stabil alap és a Codex-másolat fájlonkénti különbsége.
- A v1–v3 helyreállításban pótolt fájlok pontos eredete.
- Tesztfájlok, tesztadatok és eredménynaplók helye.
- Buildszkriptek, konfigurációk és környezetek helye.
- A csomagolás megismétléséhez szükséges parancsok.
- Appbeállítások és importált adatok tárolási helye.
- A Traktor-adatforrás útvonalának konfigurálhatósága.
- Exe-k mérete, módosítási ideje és SHA-256 értéke.
- Kiadásonkénti forrásazonosító, vagy annak rögzítése, hogy ilyen nincs.
- A még meglévő és a már hiányzó történeti fájlok elkülönítése.

Ez a dokumentum a történeti áttekintést és a biztosan megnevezett
útvonalakat tartalmazza. A hiányzó fájlszintű adatokat nem helyettesíti
feltételezett fájlnevekkel vagy meg nem történt ellenőrzésekkel.
