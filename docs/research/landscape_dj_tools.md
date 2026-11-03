# What else is out there: free DJ library and "next track" tools

Searched 2026-11-03 (web search, no downloads, no hands-on testing). Statements are from the cited pages, many
of them forum posts or vendor text; "not found" means I did not find it, not that it does not exist.
Question: is anyone else building free software for tempo-adjusted keys / BPM and next-track suggestions?

## Free or open source

| Tool | What it does | Relation to SongSelector |
|---|---|---|
| [Mixxx](https://github.com/mixxxdj/mixxx) (open-source DJ software) | Sort the library by key. A 2024 Google Summer of Code project added colour-coding of the Key column and a *Track Similarity* column from key and BPM ([report](https://mixxx.org/news/author/daniel-fernandes); whether it shipped: not checked). A request for "list all songs key-compatible with the playing track" has been open since 2010 ([#5655](https://github.com/mixxxdj/mixxx/issues/5655)). Auto DJ choosing by key: not found; a third-party script transposes the next track to match ([rdircio/autodj](https://github.com/rdircio/autodj)) | Closest open-source relative, but it is a player, not a library companion, and has no audio-similarity |
| [Rapid Evolution](https://en.wikipedia.org/wiki/Rapid_Evolution) | Free harmonic library tool: stores BPM, key, styles; shows songs within BPM range, in key and of similar style; source released 2013; version 3 still beta in 2024 ([Digital DJ Tips](https://digitaldjtips.com/?p=4033)) | The most similar idea (BPM + key + style filtering); old, no audio embeddings, no Traktor-NML link |
| [KeyFinder](https://alternativeto.net/software/keyfinder-1/about) | Open-source key detection | Detection only |
| [Trainspotter](https://forum.djtechtools.com/t/anyone-use-trainspotter-v2-to-get-track-info-from-beatport-for-your-traktor-library/31595) | Edits Traktor's collection file; dynamic playlists, relocate files. Harmonic suggestions: not confirmed | Same data source (collection.nml), different goal |
| [Traktor Bridge](https://community.native-instruments.com/discussion/47624/traktor-bridge-free-export-nml-playlist-to-recordbox-database-xml-m3u-or-directly-on-usb-stick) | Free: exports Traktor playlists to Rekordbox XML / M3U / USB | Migration only |
| [Mixgraph Pitch & Tempo](https://www.mixgraph.io/tools/pitch-tempo) | Web calculator: key shift and BPM change when key lock is off (about 5.95 % tempo = 1 semitone; 128 BPM + 1 semitone is about +7.6 BPM) | One track at a time; SongSelector does it for the whole library at the chosen master tempo |

## Open-source experiments with audio embeddings (small, mostly personal)

- [DJ AI (ivole32/dj-ai)](https://flavortown.hackclub.com/projects/3694): learns transition patterns from real DJ sets and
  combines them with BPM, energy, danceability and key to suggest track sequences. No Traktor/Rekordbox link mentioned.
- [DataJockey](https://github.com/hamo81558-coder/DataJockey): Essentia features and Effnet embeddings over a 4,000-song
  collection, nearest tracks by Euclidean and cosine distance. Same idea as SongSelector's similarity map.
- [AudioMuse-AI](https://blog.elest.io/audiomuse-ai-free-open-source-alternative-to-spotify-ai-dj/): analyses tempo, energy, mood and a
  neural embedding of a self-hosted (Jellyfin) library, builds playlists and similarity search. Not DJ software.
- [Embeat](https://github.com/gdstudio-org/Embeat/wiki): Spotify audio features plus playlist co-occurrence. Not a local library.

## Research

[Bittner et al., ISMIR 2017, automatic playlist sequencing and transitions](https://ir.webis.de/anthology/2017.ismir_conference-2017.55);
[DJ AI, Sabanci 2025](https://research.sabanciuniv.edu/id/eprint/52373/) (key, tempo, energy, graph optimisation of the order);
[Ishizaki et al., ISMIR 2009](https://ismir.net/conferences/ismir2009.html) (tempo adjustment by a "user discomfort" measure);
[ISMIR 2013](https://archives.ismir.net/ismir2013/paper/000210.pdf) (analysis of real DJ mixes). No open-source set generator was found.
Related: [Castellon et al. 2021](https://arxiv.org/abs/2107.05677v1), [van den Oord et al. 2013](https://papers.nips.cc/paper/5004-deep-content-based-music-recommendation).

## Commercial (for comparison)

- **Rekordbox Related Tracks / Match**: suggestions from the master deck by key, BPM, genre and artist, in groups; users
  call it too broad and say it cannot tell what goes well together ([Rekord.cloud](https://Rekord.cloud/wiki/similar-tracks),
  [Reddit](https://redlib.groet-infra.nl/r/Rekordbox/comments/1k72rgw/which_song_next/)). Pioneer's exact rules: not found.
- **djay Pro Match**: within about 10 BPM and same or adjacent Camelot key, closest BPM first (a user's account, not documentation)
  ([forum](https://community.algoriddim.com/t/full-blown-match-feature-like-related-tracks-in-rekordbox/23883)).
- **VirtualDJ LiveFeedback / GeniusDJ**: suggestions from what other DJs commonly play after the current track
  ([overview](https://dj.studio/blog/dj-software-ai-music-suggestions)).
- **Lexicon DJ**: paid library manager that syncs Serato, Rekordbox, Traktor, VirtualDJ and Engine DJ and converts smart
  playlists between them ([walkthrough](https://wearecrossfader.co.uk/blog/lexicon-music-management-for-djs/)).
- **Mixed In Key**, **DJ.Studio Automix** (orders tracks by key): paid.
- Traktor: compatible-key colouring only; a feature request for key/BPM track suggestions is open on the NI community
  ([thread](https://community.native-instruments.com/discussion/33900/new-feature-idea-matching-key-bmp-track-suggestion)).

## Reading

- Key + BPM matching is everywhere and is what the big apps offer; the complaint is that it is too broad.
- Tools that use **what the music sounds like** (embeddings) exist only as small personal or self-hosted projects, none of
  them tied to a DJ library, so far as I found.
- I did not find a free tool that combines (a) Traktor's collection and playlists, (b) keys and BPM recalculated for the master
  tempo across the whole library (with the mix types), and (c) audio-similarity search and a map. That seems to be the gap
  SongSelector fills. This is an absence in a limited web search, not proof.
- The research community's version of "next track" learns from real DJ sets (DJ AI, ISMIR work); that is the direction of the
  stored plan to feed the ordered playlists into a next-track model.
