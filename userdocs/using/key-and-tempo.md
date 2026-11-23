# Keys at the master tempo

With **Key Lock off**, playing a track faster raises its pitch, and so its key. A track in 8A at 120 BPM is no
longer in 8A when you play it at 128. SongSelector works this out for every track in your library.

## Set the master tempo

Type the tempo you are playing at into **Master tempo** above the List. Everything key- and speed-related follows
it straight away.

<!-- screenshot: Master tempo box and key columns -->

## The columns

| Column | Meaning |
|---|---|
| *Original BPM*, *Original Key* | The track as it is, from your DJ software or the file's tags |
| *Speed change* | How much faster (+) or slower (−) the track plays at the master tempo, as on the pitch fader (`+6.2%`) |
| *New Key* | The key at the master tempo, in musical notation |
| *Camelot Key New* | The same in Camelot notation (8A, 9B…) |
| *Open Key New* | The same in Open Key notation (as in Traktor) |

Right-click a column header to show or hide columns.

## Finding what mixes in key

- On the [similarity map](../sound/similarity-map.md), *Edges* draws lines to **harmonic partners** (perfect match,
  ±1 on the Camelot wheel, scale change, energy boost and more), using the keys at the master tempo.
- *Closest matches → harmonic only* lists only the similar tracks that also mix in key.
- *Advanced Search* on *Speed change* finds tracks that stay within a pitch range, for example
  *within ± 8 %* of the master tempo. See [Searching](search.md).
