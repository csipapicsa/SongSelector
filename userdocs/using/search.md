# Searching

## The search bar

Type into **Search** above the List.

| Type | Finds |
|---|---|
| `tribal` | The text in the columns ticked under *Search Columns* |
| `color:blue` | Tracks with that colour from your DJ software |
| `color:red,orange` | Either colour |
| `-color:blue` | Every track *except* blue ones |
| `color:none` | Tracks without a colour |
| `sscolor:blue`, `-sscolor:none` | The same for SongSelector's own colour |

Colour names: red, orange, yellow, green, cyan (also *aqua*), blue, indigo, violet (also *purple*), pink, brown,
grey, none.

## Advanced Search

*Advanced Search* adds rules with numbers, for example *own rating at least 4*, and on *Speed change*:

- *within ± (%)*: tracks that play at most that much faster or slower at the master tempo, for example
  *within ± 8 %*. It follows the master tempo as you change it.
- *outside ± (%)*: the opposite.

And on *Match*, how well a track matches a [description search](../sound/describe.md), in percent: for example
*Match at least 30* keeps only the close results. The rule filters only while the List shows description results;
otherwise it lets every track through. Set *Top* to *All* to filter every analysed track, not just the top ones.

Set a rule's column to *None* to switch it off without losing it.

Want to keep a search? Save it as a [smartlist](playlists.md#smartlists).

## Search by what it sounds like

The **Describe a sound** bar searches by sound instead of tags. See
[Search by description](../sound/describe.md).
