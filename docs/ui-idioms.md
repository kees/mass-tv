# Mass TV: UI idioms (how things look and respond)

The visual and interaction rules every screen follows: focus, selection,
activation, loading, and missing things. Companion:
[ui-flows.md](ui-flows.md) (which screens exist, how they connect, and
what each key does there).

## 1. Focus and selection: two states, never mixed up

**Focus** (where the cursor is) is always blue-bordered:

- **Grids and card rows** (PosterCard in MarkupGrid/RowList): a 4 px blue
  frame around the **whole card**, cover plus title and subtitle, drawn
  inside the card's slot (grids clip anything outside their bounds). The
  caption is inset 12 px so the frame doesn't touch the text. Moving
  the cursor, the new card's frame appears at once and the old one fades
  out, in grids and between a card row's rows alike (during a row
  change the new card keeps its frame through the slide).
- **Track lists** (TrackRow) and **menu rows** (MenuRow, in OptionsMenu,
  Settings, the profile picker, and the link screens' lists): the list's
  gray (#232A33) inside a rounded blue ring (`images/focus_row.9.png`).
  A row whose second line is empty centers its title.
- **Rows of text** (NavBar, Library's tabs and its View/Sort labels,
  TabRow, LetterRow, ButtonRow): the focus ring, a rounded translucent
  fill with a blue border (`images/focus_ring.9.png`, placed by
  `source/lib/FocusRing.bs`), hugging the text. It shows only while that
  row has focus.
- **Text colors are shared** (`focusring.*`): plain items gray #9A9FB0
  (pill items light #D8DCE6, see below), white under the ring; selected
  items blue #5A8DEE, and under the ring a stronger, darker blue #3A73E0
  (distinct from the border).

**Selected** (the current screen, the shown tab, an "on" switch such as
Shuffle or Favorite) is **blue text only**: no underline, no frame. It
stays blue under the cursor's ring.

**Something to press** looks pressable at rest. Outside the nav bar,
grids, and lists, every clickable thing (ButtonRow buttons: Detail's,
Now Playing's, the server screen's Link, Cancel, and Now Playing; MenuRow
rows: Settings, the server screen's servers and address, the link
screen's fields, the profile picker's profiles) rests on a **pill**: a
faint rounded fill (#1C232C, `images/pill.9.png`, `focusring.PILL_URI`)
with light text (#D8DCE6, `focusring.PILL_TEXT`). Three levels, never
mixed up:

- **Gray text, no fill** (#9A9FB0): information (descriptions, status,
  hints). Never clickable.
- **Greyed button** (dim text #5A6270 on a half-faint pill): can't be
  used right now (Now Playing's More with nothing loaded). It still
  takes the cursor, so moving along the row doesn't skip; OK does
  nothing.
- **Pill**: can be pressed. A button's pill fills its slot.
- **Blue ring**: where the cursor is; it takes the pill's place (same
  shape), so nothing moves.

The nav bar, Library's tab/View/Sort row, grids, track lists, and
OptionsMenu (a menu is a list: its rows set `plain`) have no pills: where
they sit already says they're navigation or choices.

## 2. Activation and movement

- **Moving the cursor never changes content.** Tab-like rows (the nav
  bar, Library's tabs, its letter row) switch on **OK**. Left/Right
  within a row, Up/Down between rows.
- **OK on a navigation row goes down to what it shows:** it shows the
  choice and moves the focus one level down, onto that choice's first
  level. The nav bar: the screen's first level (Home's first row,
  Library's and Settings' tab rows on the shown tab, Search's keyboard,
  Now Playing's Play/Pause button, Queue's current item). Library's
  tabs: the letter row on its shown letter (Albums, Artists), else the
  first item (Playlists, Tracks); OK on the tab already shown reloads it
  and goes down the same way. Settings' tabs: the tab's first row. With
  nothing to land on (an empty tab), the focus is back on the shown
  tab. **The letter row is the exception:** OK shows the letter and
  keeps the focus on the row, so subsets can be compared by stepping
  along the alphabet. **Down onto nothing stays put:** Down toward an
  empty listing (an empty tab or letter, a search with no results, an
  album with no tracks) leaves the focus where it is. Back is the
  reverse of going down (below): up one level, on the shown choice.
- **OK opens** an item (album, playlist, artist, folder, and a track: its
  Track page); only what has no page (a radio station, a podcast
  episode) plays on OK. **Play/Pause** on an item focused in a list,
  grid, or row of cards plays it right away, even over what is playing:
  a track alone (MA's "play now": what was queued after the current item
  still follows), as MA's web UI plays a picked track, also on an
  album's or playlist's track list; anything else replacing the queue.
  On the very track that's playing (matched by uri: the Roku's queue
  item, else MA's current one), or an album card of the playing track's
  album, it pauses and resumes instead. Only while the cursor moved in
  the last 60 s (a key press, then the focused item changed; a screen's
  own first focus doesn't count, so it starts expired at launch):
  Music Assistant pauses and resumes a Roku by pressing its Play key
  over ECP, which the app can't tell from the remote's, so a Play with
  no recent cursor move pauses or resumes, or starts MA's queue. The whole
  album comes from its page's Play, or a Track page's More, "Play album
  from here".
  Anywhere else (buttons, the nav bar, menus and the text panel, Now
  Playing, Queue, Lyrics) it pauses and resumes what's loaded, or starts
  MA's queue when nothing is. Held, it opens Now Playing. The playback
  keys (Play/Pause, rewind, fast forward, instant replay) work over a
  menu or the text panel too; a menu takes every other key.
- **Held keys act when the hold is reached, not on release.** Every key
  with a hold action works the same way (`keys.handle`/`keys.held`, one
  hold timer in MainScene): a press arms a timer (0.6 s, `keys.HOLD_MS`);
  if the key is still down when it fires, the hold action runs right
  then, and the key's release is ignored; a release before that is a
  tap, acting on release. Play/Pause held: Now Playing; Rewind and Fast
  Forward held: previous and next track (tapped: seek 10 s back or
  forward). A new held key goes through the same path, never a
  duration measured at release.
- **Key hints** use one vocabulary (`source/lib/Hints.bs`): "OK: <what
  it does>", "Play/Pause: tap to <what>, hold to view Now Playing",
  "Back: <where it goes>", stacked a key per line and centered, so the
  OK line (which changes as the cursor moves) reads on its own. Now
  Playing has its own two lines ("Play/Pause: tap to pause or resume,
  hold to view Now Playing" ("tap to play it again" once the queue
  ended), "Rewind/Fast Forward: tap to seek 10 s, hold to change
  track"). Elsewhere a hint lives only in the band at the bottom that
  the Now Playing bar uses, and only on list screens, whose lists stop
  above that band so it's empty while nothing plays; grids and rows of
  cards run to the bottom of the screen (the next row peeking there),
  so they get none. It shows while the bar is hidden, for where the
  focus is (a screen's `keyHint`; none with the focus off the screen's
  own widgets: the nav bar, a menu). The list screens: album and
  playlist pages (the buttons: "OK: play the album", "OK: turn shuffle
  on", ..., "Play/Pause: tap to resume the queue, hold to view Now
  Playing"; the
  track list: "OK: open the track · Play/Pause: tap to play this track,
  hold to view Now Playing · Back: go to the buttons", "play the
  album/playlist from this track" with the profile's "Queue collection
  when playing a track") and Library in List view ("OK: open the album
  · Play/Pause: tap to play the album, hold to view Now Playing"). Not
  on grids, rows of cards, artist or Track pages.
- **A blue (on) button is a switch:** pressing it turns it off, and it
  never also starts something. Shuffle on album/playlist pages switches
  MA's queue shuffle (`player_queues/shuffle`); Play and track picks pass
  it to play_media, which otherwise turns shuffle off for albums.
- **A yes/no setting is a checkbox row** (MenuRow with a `checked`
  field): a 30 px box at the row's left, filled blue with a white ✓ when
  checked, an outline when not (light, white under the ring); the label
  names the setting without ": on/off", and OK flips it. The screen
  reader says "checked" or "not checked" before its description. Rows
  with more than two values (the screensaver's minutes, the log level)
  stay labels with their value, stepped by OK.
- **Tab rows** (Library's; Settings' TabRow): text tabs, the shown one
  blue, the cursor in the focus ring; OK shows a tab (moving the cursor
  never changes content) and goes down to it (above).
- **Buttons don't move when a label changes:** a ButtonRow button whose
  label varies (Play/Pause; Repeat, Repeat all, Repeat one) gets
  `sizeHints` listing every label it can show; its slot fits the widest.
- **Aiming between rows of different kinds:** Up and Down go to the
  item most directly above or below the cursor, not to a remembered
  spot: nav bar <-> any screen's top widget, a Detail page's buttons <->
  its rows of cards, Search's pill <-> its results, and Library's tab row
  <-> its letter row <-> its grid. It's worked out from the widgets
  themselves (`source/lib/Aim.bs`): a grid's focused column, a card
  row's focused card (its scroll followed from `rowItemFocused`, since
  list items can't be measured), a button row's focused button, a tab
  row's cursor tab (Settings' Profile and This TV both sit under Home).
  Full-width rows
  (track lists, the queue, menus) have nothing in particular above them:
  Up from one goes to the current screen's nav entry, and Down onto one
  keeps its cursor. Screens use `aim.moveFocus(from, to)` to move between
  their own widgets; a screen may still report `focusX` and take `aimX`
  itself (Library's tab row, drawn as text).
- **Down onto a shorter grid row** goes to its last card, the closest
  one, rather than being refused.
- **Wrapping:** screens and menus that are a closed set of areas wrap
  Up/Down (OptionsMenu; the server screen's list, address row, and Now
  Playing area; the link screen's rows). Rows of text and buttons wrap
  Left/Right: the nav bar (the profile name <-> Home), button rows (each
  of Now Playing's two rows on its own: Favorite <-> Prev, More <->
  Queue; Detail's buttons), Library's tab row (Sort <-> Playlists), its
  letter row (Z <-> All), and Settings' tabs (This TV <-> Profile). Not
  a button row that hands its ends to a neighbor (`passEdges`, the
  server screen's address row), and not card rows or grids (they
  scroll).
- **A field beside its buttons:** an editable value (the server address)
  is a MenuRow pill with its buttons in a ButtonRow on the same line
  (`passEdges` lets Left/Right cross between them).
- **Choosing jumps ahead:** when choosing something fills in the next
  step, the cursor moves there (a server picked from the list fills the
  address and lands on **Link**).
- **Up from a screen's top edge** goes to the nav bar; Down from the nav
  bar returns to the screen's last focused widget, aimed below the nav
  cursor.
- **Back goes up one level of navigation, the way Up would, toward the
  nav bar**, landing on what's shown there (the chosen item, not
  wherever the cursor was last):
  1. **A screen's own levels first:** Library's grid or list goes to the
     letter row (on the shown letter; Artists and Albums), the letter row
     to the tab row (on the shown tab); Browse goes to the parent folder;
     a Detail page's track list or artist rows go to its buttons (the one
     last used), and Back there closes the page.
     The screen consumes Back while it has a level to go up to.
  2. **A screen opened on top** (Detail, Now Playing over another screen)
     closes, back to the screen beneath, with the focus where it was
     there. This comes before step 4: with the nav bar focused over such
     a screen, Back still closes it.
  3. **A root screen's top level** goes to the nav bar, on that screen's
     entry ("Library, 2 of 7, current page").
  4. **On the nav bar,** Back goes Home, the cursor staying on the bar
     (on Home's entry); on Home's entry it asks "Exit Mass TV?" (Roku
     certification 4.6).
  Screens without the nav bar (the link screens, the picker) go
  straight to their table entry in ui-flows. New levels in a screen
  follow the same rule: Back to the level above, on its shown item.
- **Library opens with focus on its tab row** (a second level of
  navigation). On a Detail page, Left/Right in the track list jumps to the
  button row; Down returns to the same track.

## 3. Menus

- **Every menu has an on-screen route; Mass TV doesn't use the Options
  (\*) key.** Roku OS takes \* for its own panel whenever media plays.
- **Menus of choices use `widgets/OptionsMenu`** (our modal list: labels
  can change while it shows, Up/Down wrap, Back closes, the playback
  keys pass through), not a Roku dialog. Rows are `widgets/MenuRow`
  with the text-row colors (gray/white, blue when selected), a darker
  backdrop, width fitted to
  the labels (`sizeHints` when labels change). Screens open one with
  BaseScreen's `showMenu(title, labels, handler)`: OK closes it and calls
  `handler(index)`, Back closes it, and it goes away if its screen is
  covered or removed. Users: a Detail page's and Now Playing's More, a
  queue row's OK, and Library's Sort (its own, since it relabels while it
  shows).
- **Library's Sort menu** (OK on Sort) lists the tab's fields (mirrored
  from MA's web UI, `source/lib/LibrarySort.bs`) in their natural
  direction, plus "Reverse order" and "Favorites only"; each tab
  remembers its sort, its Favorites only, and its grid/list View, per
  profile. Fields are labeled as they'd
  sort in the current direction ("Name (Z–A)" while reversed), the
  current one blue; picking one applies it (keeping the direction) and
  closes the menu; the switches (blue when on) apply at once and keep it
  open, the list re-sorting behind it.
- **Long text is read in `widgets/TextPanel`** (via BaseScreen's
  `showTextPanel`): the menus' panel style, the item's name as title, the
  text in the medium font, sized to the text but never taller than the
  screen with Close in view; a longer text scrolls with Up/Down while
  Close keeps the focus ("Up/Down to scroll" shows then). Close or Back
  closes it.
- **A menu never repeats what's already on screen:** More leaves out
  its screen's buttons' actions (`showItemOptions(item, skip)`).
- **"More"** is the button name for an item's menu (Detail pages, Now
  Playing), never "Options".
- **Roku dialogs** (native) only where the jolt helps or the system's
  own is better:
  - **"Are you sure?"** (Settings: unlink a profile, forget everything)
    stays native on purpose: the sudden change of look makes the user
    stop and check before something that can't be undone. Keep every
    such confirmation native, and never use one for an everyday choice.
  - **"Exit Mass TV?"** (Roku certification 4.6).
  - **Keyboards** (StandardKeyboardDialog); the password keyboard adds
    a "Show / hide password" button (hidden by default).

## 4. Showing there is more

- **Track lists fade the edge row** when rows continue past it
  (ListFade, fading with the scroll). Only track lists fade; other lists
  (menus, the profile picker, the server list) show just the scroll
  indicator.
- **Anything longer than its area gets a scroll indicator** at its right
  edge: every list, grid, and text that can scroll vertically. The
  indicator (widgets/ScrollIndicator: a thin track and a thumb, just
  visual) shows how long the whole is (the thumb's share of the track)
  and where the view is (the thumb's position); it hides itself when
  everything fits, so give it to an area that only sometimes overflows
  too. Its length is the whole thing's, not what has loaded: Library
  gives the listing's length once known (`total`). Use the reusable
  pieces rather than a new bar: `widgets/ListScroll` follows a
  MarkupList or MarkupGrid (Library's grid; with `clip`, the profile
  picker and the server list); `widgets/ListFade` includes one for a
  track list; a scrolling text sets ScrollIndicator's fields itself (the
  long-text panel, the Lyrics screen).
- **Exception: stacks of horizontal rows get no scroll indicator** (Home,
  Search, a Detail page's rows of cards). Their rows scroll up under a
  fixed focus, and the next row peeking from below shows there is more
  (next bullet). A list that never scrolls (a fixed set of fields, a menu
  that grows to fit its items) needs none either.
- **Rows and grids let the next column or row show cut off** at the
  screen edge (Home and an artist's Detail rows keep the focused row at
  the top, fixed focus, so the next row peeks from below and Down scrolls
  the rows up under the focus; Library's grid keeps the focus in two rows
  and lets the third show past the bottom, through its
  `itemClippingRect`).
- **Browse shows a breadcrumb** ("Browse › Example Music › Playlists", the
  current level bold) and "(Back to go up)" below the top level.

## 5. Waiting on Music Assistant

- **Every screen area filled by an MA reply shows a `LoadingIndicator`**
  (set `active` from request to reply): it appears after 0.3 s and says
  "Still waiting for Music Assistant…" after 8 s. Only first loads use it,
  not background refreshes or later pages.
- **Long listings are their full length from the start** (Library): once
  the length is known, cards and rows not read yet show as empty
  placeholders (the missing-cover emblem, no text) that fill in as their
  pages arrive, so a held Down scrolls on without stopping at what has
  loaded (Roku's lists stop a held scroll at the content's end as it was
  when the hold began). Placeholders go no more than 360 items past the
  focus, and pages are read under the focus wherever it goes. OK on a
  placeholder does nothing; the screen reader says "N of <length>".
- **Play requests** set `m.global.playPending` (`actions.play`); the Now
  Playing bar then shows the chosen item's title, artist, and cover (the
  rows' 80 px URL, so usually cached; else a spinner), with "Loading…" and
  a spinner in the time slot, until MA's play deep link arrives, the
  request fails, or 20 s pass (then a toast).
- **Time-slot text:** "Loading…" and "Paused · 0:10 / 2:26" sit by the
  time, never before the artist.

## 6. Missing things

- **Missing covers show the dim Mass TV emblem:** 25% strength in track
  rows, untitled cards, a Detail page's header, and Now Playing, its
  ambient view, and its blurred backdrop (their own 520 px image; the
  backdrop blurs it like a cover); 8% under a card's large initials (up
  to two letters, as MA's web UI shows: the first letters of the first
  two words, or the first two of a one-word name, punctuation skipped;
  `images.initials`). Failed cover loads fall back the same way, and so
  do stand-ins (Music Assistant's logo, which it sends for a coverless
  item, and the blank covers some streaming services send:
  `images.isStandIn`). Every cover is a `widgets/CoverArt`, which owns
  this; use it for any new cover.
- **Empty screens and lists say what to do** (e.g. Home's "Nothing here
  yet. Play something from Library or Search, or check that a music
  service is connected in Music Assistant.").

## 7. Wording

- **"Link", never "sign in" or "log in":** Mass TV works without an
  account (it plays what MA sends), so connecting an MA account is
  linking a profile: "Link Music Assistant Profile", "with your TV" / "with
  your phone", "Profile name", "Link another profile", "Unlink this
  profile", "link expired". Only Music Assistant's own page says "log in".
- **Name this TV by the Roku's own name** (from the device), as Music
  Assistant does for its player: "this TV (Living Room Roku)".
- **"Endless mix"** for MA's radio_playlist feature (as in MA's web UI).
- **Music Assistant's text goes through `fonts.label`** (titles,
  artists, albums, names, descriptions), so CJK and emoji switch the
  label to the bundled font; pass `true` for a bold label. Mass TV's own
  English strings set `text` directly.
- **Items read the same everywhere:** text rows and the Now Playing bar
  use the same title (with its version) and second line ("artists ·
  album").
- **A count's noun agrees with it:** "0 tracks", "1 track", "2 tracks",
  on screen and in what the screen reader says. Never join a number and
  a fixed plural; use `util.counted(n, "track")` (and its third
  argument for an irregular plural: `util.counted(n, "match",
  "matches")`).

## 8. Brand

- The logo's text is Roboto Bold (the font of Music Assistant's web UI),
  drawn into the images by `tools/make_images.py`. The nav bar's "Mass
  TV" is the logo's wordmark image (`images/wordmark_nav_$$RES$$.png`),
  not system-font text.
- An image with text is made at the size it's shown, once per UI
  resolution (`_fhd`, `_hd`, picked by `$$RES$$`): Roku shrinks images
  without smoothing, which makes text jagged.
- All artwork is broadcast-safe (every channel within 16..235);
  `tools/make_images.py` fails on an out-of-range pixel.

## 9. Reporting the focus

The focus is reported from one place, for its two audiences: said for
the screen reader, and logged at DEBUG in one format (category `focus`,
the widget kind as the message, and the screen plus what the widget
knows: index, id, label, kind, uri, name, and `said`, what was said).
Device tests confirm where focus is from it before pressing OK, and the
e2e tests check navigation with it (`is_focus` in `tools/e2e_sim.py`)
and that no move goes unsaid. Rows of text also log their focus ring
appearing and going away (category `ring`, `focusring.logShown`), so
tests can check that the ring follows the focus.

**Widgets describe; the focus tracker reports** (`source/lib/Focus.bs`,
MainScene's tracker):
- Every focusable widget keeps a `cursor` field describing what's under
  its cursor (`focustrack.describe`: its kind, the cursor's place, the
  words for it, the log's data, the context to say when the focus
  arrives, and the group, such as a row of cards, with its name). It
  never speaks or logs its own focus. Lists get theirs from BaseScreen's
  `speakLists(lists, widgets)` (which names each list's kind); a screen
  calls `speakList(list)` when items change under the cursor.
- Every change of which node has the focus goes through
  `focustrack.set(node)`, never `setFocus` directly.
- The tracker follows the focused widget's `cursor` and, once the focus
  settles (20 ms, so a focus that is set and then aimed, or a list
  reporting its item twice, is one move), applies one rule for every
  widget:
  - **a move** (the focus on another widget, or the cursor on another
    place) is said and logged, with the widget's context when the focus
    arrives on it and the group's name when the cursor enters another
    group;
  - **new words at the same place** (a placeholder filled in, a tab
    becoming the shown one, Play turning into Pause) are said, not
    logged as a move;
  - **nothing under a cursor, or no focus** (a dialog, Now Playing's
    ambient view) reports nothing; the last widget stays watched for the
    focus coming back.
- News that isn't about the focus (a toast, a status line, "now
  playing") uses `speech.say`.
- A widget is still aimed before it takes the focus where it can be
  (Down from the nav bar: the screen's `aimTarget`; between a screen's
  own rows: `aim.moveFocus`).

## 10. Screen reader (Roku's Audio Guide)

- **Only Roku's dialogs and keyboards speak themselves.** Everything
  else sets `muteAudioGuide`; focus moves are said by the focus tracker
  (section 9), everything else through `speech.say`
  (`source/lib/Speech.bs`).
- **Lists and grids** (BaseScreen's `speakLists`) say the focused item
  when it moves or the list gets focus: a row list's row name when the
  cursor enters a row or the list gets focus, the item's title, its
  second line, "selected" for a blue row, its place ("button 3 of 12";
  "button 7" while more may load), then any help text ("Recently played,
  Ashes, Josh Woodward, button 3 of 12"; "Link another profile, button 2
  of 3, Link another person's..."). The second line is the item's
  `AUDIO_GUIDE_SUFFIX` when set (track rows, `speech.describeRow`: "now
  playing", artists and album, the length in words), else its
  description; help text is `speechHint` (`speech.setHint`: Settings'
  descriptions). A screen whose list items arrive or change under the
  cursor (a page loading, a placeholder filled in) calls
  `speakList(list)`.
- **Our widgets:** the nav bar ("Library, 2 of 7, current page"),
  button rows ("Shuffle, on, button 2 of 5"; "unavailable" when greyed),
  tab rows ("Albums, tab 2 of 4, shown"), the letter row ("Letters, D, 6
  of 28, shown"), menus (title first, then "Play next, button 1 of 4",
  "selected" for blue rows).
- **Context goes first when the focus arrives:** a widget's context is
  said before its focused item when the focus arrives on it (a
  ButtonRow's `context`: a Detail page's title, kind, and artist; Now
  Playing's track; a text panel's whole text; a menu's title; the letter
  row's "Letters").
- **News is queued, moves cut in:** toasts, status lines, and a new
  track on Now Playing are said after what's being said; a focus move
  interrupts.
- **Words, not symbols:** " · " becomes a pause, an en dash "to", and
  lengths are words ("3 minutes 20 seconds": "3:20" reads as a time).
- **Test by the log:** every `speech.say` logs `speech say` with its
  text, and every focus move logs `focus` with what was said (section
  9), so e2e and device steps show what would be heard. Roku's own
  speech (dialogs, keyboards) isn't logged; only listening checks it.
