# Mass TV: screens and flows (user stories)

How Mass TV's UI behaves: what each screen is for, how people get there,
and what every key does. Companion:
[ui-idioms.md](ui-idioms.md) (how things look and respond: focus vs
selected, the focus ring and frames, menus, loading and missing-cover
rules, wording).

## 1. Concepts

- **Player and client.** Mass TV is two things at once:
  - a **player** that Music Assistant (MA) sends music to over the
    Roku's network control (ECP). This needs no account: an admin adds
    MA's "Media Assistant (Roku)" provider and points its App ID at Mass
    TV (883989 for the Roku Channel Store app, `dev` when sideloaded);
  - a **client** for browsing, searching, the library, and the queue,
    which needs a **linked Music Assistant profile** (an MA user and a
    token stored on the TV).
- **Linked / unlinked.** A TV with no stored profile is **unlinked**: it
  still plays whatever MA sends, but everything else needs a linked profile.
- **Profiles.** Each person links their own MA profile (their own
  streaming accounts and library, via MA's per-user provider filter).
  With more than one linked, the TV asks "Who's listening?" at start.
- **Wording.** Always "link a profile", never "sign in" or "log in".
  Mass TV's text never says "log in"; only Music Assistant's own page
  does. The account field is "Profile name".

## 2. Screen map

| Screen | Purpose | Reached from | Back goes to |
|---|---|---|---|
| **Link Music Assistant Profile** (`setup`) | Choose the Music Assistant server | unlinked start (beneath Now Playing); Settings > Link another profile; "Link a new profile" (the button under the picker's list); unlinking the last profile; Settings > Forget everything; a profile whose link expired | exit dialog (it's a root) |
| **Link Music Assistant Profile, on <server>** (`link`) | Link a profile on the chosen server, with the TV or a phone | Link on the server screen | the server screen |
| **Who's listening?** (`profiles`) | Pick a linked profile | start with 2+ profiles; Settings > Switch profile; unlinking one of several; the server screen's Cancel | exit dialog (root) |
| **Home** | Recently played, then MA's recommendation rows | start with one profile; nav bar | the nav bar (Home), then the exit dialog |
| **Library** | Playlists, Albums, Artists, Tracks | nav bar | grid or list -> the shown letter (Artists, Albums) -> the shown tab -> the nav bar (Library) -> Home |
| **Browse** | MA's provider folders (breadcrumb trail) | nav bar | parent folder, then the nav bar (Browse), then Home |
| **Search** | Search MA with the keyboard (voice on voice remotes) | nav bar | the nav bar (Search), then Home |
| **Detail** | An album, playlist, artist, podcast, audiobook, or track (the Track page) | OK on such an item anywhere, a track included (a track row in an album's or playlist's list too) | previous screen |
| **Now Playing** | What's playing, transport buttons, up next | nav bar; unlinked start; playback starting on a link screen or the picker; the server screen's Now Playing button; launched by MA to play | on top of another screen: that screen; from the nav bar: the nav bar (Now Playing), then Home |
| **Queue** | MA's queue around the current track | nav bar; Now Playing's Queue button (on top of it) | on top of Now Playing: Now Playing; from the nav bar: the nav bar (Queue), then Home |
| **Settings** | Profile and This TV settings, help, about | the profile name in the nav bar | rows -> the shown tab -> the nav bar (the profile name) -> Home |

Back from the nav bar goes Home with the cursor staying on the bar (on
Home's entry); Back there asks to exit (ui-idioms, "Back goes up one
level").

The nav bar (the Mass TV wordmark; Home, Library, Browse, Search, Now
Playing, Queue; and at the right end the profile name, which opens Settings)
shows on every screen except the two link screens and the picker, and
never while unlinked. The profile name is the bar's last entry (Right
from Queue), blue while Settings shows; "OFFLINE" in red sits to
its left while Music Assistant can't be reached.

## 3. Starting the app

1. **Unlinked** (no profile stored, or a fresh reset): **Now Playing**,
   on top of the server screen. With nothing playing it says "Play
   something from Music Assistant" and "Add this TV (<Roku name>) as a
   Player in Music Assistant". Back goes to the server screen.
2. **One profile:** Home, with that profile active.
3. **Two or more:** "Who's listening?": the title centered a quarter of
   the way down the screen, a **Link a new profile** button (to the
   server screen) three quarters of the way down, and the profiles as a
   list around the middle, growing up and down with as many rows as fit
   between them (five at 1080p); more scroll, with a scroll indicator.
   Up/Down go from the list's ends to the button and wrap; Left/Right
   from the list go to the button. When the profiles are on more than
   one server, every row names its server after a dot ("Alice  ·  Music
   Assistant (den)"). Picking a profile opens Home. A profile whose link
   expires within 30 days shows "(link expires soon)"; one whose link
   has expired shows "(link expired)", and picking it says "That link
   has expired. Link the profile again." and opens the server screen
   instead. The cursor starts on the profile used last.
4. **Launched by MA to play** (MA sent a play while Mass TV wasn't
   running): with one profile, Now Playing; with several, the picker,
   and the profile picked opens Now Playing (later ones, as from Switch
   profile, open Home); unlinked, as in 1.
5. Every start renews stored links nearing expiry (see 9).

## 4. Linking a profile

Linking takes two screens: choose the server, then link on it.

### 4.1 Server screen: "Link Music Assistant Profile"

Top to bottom:

- **Music Assistant servers broadcast on your network:** a list of the
  Music Assistant servers found on the network (mDNS `_mass._tcp`, asked
  again 10 s after each look while the screen shows), each showing its
  name and
  address ("Music Assistant (homeserver) · 192.0.2.10:8095"), the one in
  the address row in blue. Four rows show; more scroll within them, with
  a scroll indicator, and servers found later keep the cursor on its
  server. While looking: "Looking for Music Assistant on your network…";
  none found: "No Music Assistant found on your network. Enter its
  address below." **OK on a server** puts its address in the
  address row and moves the cursor to **Link**. When servers first appear
  on a screen with no address and no key pressed yet, the cursor moves to
  the list.
- **Music Assistant server (address:port):** the address, e.g.
  192.0.2.10:8095, or "Press OK to enter it" (OK opens the keyboard to
  type or edit it, e.g. 192.0.2.20:8095), then **Link**, then
  **Cancel** when another profile exists (back to the picker). The row
  starts with the last server used, if any, with the cursor on Link;
  otherwise on the address. **Link** checks the server (it must answer as
  Music Assistant) and opens the link screen for it; if it doesn't
  answer: "Couldn't reach Music Assistant at <address>."
- **Now Playing area:** "Music Assistant can play to this TV (<Roku
  name>) without a linked profile." and a **Now Playing** button that
  opens Now Playing on top; Back returns.

Up/Down move between the list, the address row, and the Now Playing
area, and wrap: Down from Now Playing goes to the list's first server,
Up from the list's first server to Now Playing, and Up from the address
row to the list's last server (the list is skipped while empty).
Left/Right move along the address row.

### 4.2 Link screen: "Link Music Assistant Profile"

The chosen server is named under the title ("on Music Assistant
(homeserver) · 192.0.2.10:8095"), above two equal halves:

- **with your phone** (left; the heading and QR code centered in the
  half, like "with your TV"; the code's top level with the Profile name
  field's, and its size set so the text under it ends as far above the
  screen's bottom as the text's left margin): a QR code, then "Scan the
  code or browse to:", its URL (on the TV's own address), and "To open
  Music Assistant for linking your profile." The code and URL take the
  phone straight to that server's Music Assistant page, which asks for
  the profile name and password; MA then hands the link back to the TV.
  Once a phone opens it: "Finish linking on your phone."
- **with your TV** (right): rows **Profile name** and **Password**, then
  a **Link profile** button centered under them (Up/Down wrap through
  all three; the cursor starts on Profile name). OK on a field opens the
  Roku keyboard; the password's keyboard hides what's typed and has a
  **Show / hide password** button (hidden by default). Filling the
  password with a profile name set, or Link profile, links. Below the
  button: "Mass TV doesn't save your password. It's sent once to Music
  Assistant for a link token, which is all this TV stores." Statuses:
  "Linking…", "Couldn't link: check the profile name and password.",
  "Finishing linking…".

Back returns to the server screen. **Success:** a "Welcome, <name>"
toast and Home, as that profile.

## 5. Playback while unlinked (or on a link screen / the picker)

On the link screens or the picker, linked or not, Mass TV keeps playing
what MA sends:

- **A new track starting** there brings up **Now Playing on top**. The
  track already playing when those screens open doesn't flip; the next
  one does.
- **Back** returns to the screen beneath and **dismisses** Now Playing
  until playback stops (track changes don't bring it back).
- **When MA stops playback,** Now Playing closes by itself, but only on
  a stop: opened by hand with nothing playing, it stays.
- **Unlinked Now Playing** shows the track, art, progress, and up next,
  with only a **Pause/Play** button; seeking, track changes, and the
  other buttons need MA's API, so they are hidden or do nothing. Its
  hint: "Play/Pause: tap to pause or resume · Back: link a Music
  Assistant profile". At a track's end the player plays MA's queued next
  track by itself.

## 6. Moving around (linked)

- **Nav bar:** Up from a screen's top edge; Left/Right move the cursor
  and wrap (the profile name <-> Home);
  **OK** switches screens (moving the cursor never does) and goes down
  into the screen's first level (ui-idioms §2); Down returns to the
  screen. Between rows of different kinds, focus aims at the item
  most directly above or below: Up from a card or button lands on the
  nav entry above it (from a full-width row, on the current screen's),
  Down from an entry on the card or button below it; likewise between a
  Detail page's buttons and its rows of cards, Search's pill and its
  results, and Library's tabs and its grid. Down onto a shorter grid row
  lands on its last card.
- **Back:** up one level (see the table): a screen's own levels, then
  the nav bar on the screen's entry, then Home's entry; there, one "Exit
  Mass TV?" dialog, noting that the music stops if something is loaded.
- **OK** opens an album, playlist, artist, folder, podcast, audiobook,
  or track (its Track page); only what has no page (a radio station, a
  podcast episode) plays on OK.
- **Play** plays the focused item at once; on a Detail page with a track
  focused, that track alone, or the album or playlist from that track
  when "Queue collection when playing a track" is checked (section 7).

## 7. Screens

- **Home:** "Recently played", then MA's recommendation rows (a third row
  peeks from below). In a row of mixed kinds, a card's second line
  starts with its kind ("Album · Josh Woodward · 2010", "Track · Josh
  Woodward · Ashes", "Artist", "Playlist · <owner>"); a row of one kind
  shows no kind. Empty: "Nothing here yet. Play something from
  Library or Search, or check that a music service is connected in Music
  Assistant."
- **Library:** tabs Playlists, Albums, Artists, Tracks; opens with focus
  on the tabs, on the tab shown when Library was last left (Playlists
  when a profile has just become active); **OK switches tabs and goes
  down to the tab:** Albums and Artists to the letter row, on the shown
  letter (All unless one was picked), Playlists and Tracks to the first
  item; an empty tab leaves the focus on the shown tab. OK on the tab
  already shown reloads it (e.g. to pick up changes made in MA) and goes
  down the same way. Right of the tabs: **View** (grid or list,
  remembered per tab and per profile; a list for Tracks, a grid for the
  others until changed) and **Sort** (remembered the same way; OK opens
  "Sort <tab>": its fields, each labeled as it would sort in the current
  direction ("Name (Z–A)" while reversed), "Reverse order", "Favorites
  only" (also per tab and per profile); picking a field keeps the
  direction and closes the menu, the two switches keep it open). Down
  from the tabs aims at the grid column below.
  **Artists and Albums** have a **letter row** under the tabs: All, #
  (a digit or symbol first), A to Z; the shown one is blue, OK shows it
  and keeps the focus on the row (the exception to going down, so
  subsets can be compared along the alphabet). A letter shows only the
  items MA sorts under it (by sort name: "The Beatles" under B,
  ARTISTSORT tags for local files, a CJK name under its
  transliteration's letter, and only between two items of that letter
  or in a run too long to see past, since the Roku can't
  transliterate). A letter lists by name (in the tab's direction if its
  sort is by name, else A–Z), and the tab row has no **Sort** while a
  letter is shown (View is then the row's last label; "Favorites only"
  shows there as a plain label when on). **All** keeps its own sort,
  any field, which comes back with it. None: "No artists under Q." ("No
  favorite albums starting with a digit or symbol."). The letter is kept
  per tab while the app runs, also when Library is left and opened
  again, until a profile becomes active. Tabs -> letters -> grid aim at
  what's below or above.
- **Browse:** MA's folders with a breadcrumb ("Browse › Example Music ›
  Playlists") and "(Back to go up)" below the top level.
- **Search:** opens the keyboard; results in rows by type.
- **Detail:** header art and info. An artist's header shows MA's
  biography for it (up to three lines, cut with "…"; nothing when MA has
  none, since a subtitle would only repeat "ARTIST"). An album with a
  description or a review (MA's `metadata.description`, then
  `metadata.review`; More > View description shows both, a blank line
  between) shows artist, year, and track count on one line and the
  start of that text on two below;
  otherwise artist · year, then track count and length. An album's info
  ends with its source as MA names it for the profile ("12 tracks ·
  44:46 · Example Music"; several joined with commas; another person's
  streaming account on a shared library album is left out, since only
  the profile's own sources count; text only, since MA's provider icons
  are SVG, which Roku can't draw). Buttons **Play**, **Shuffle** (a
  switch for MA's queue shuffle), **Endless mix** (not for podcasts and
  audiobooks), **Favorite** (a switch), **Newest first** (playlists whose
  tracks carry date added), **More** (the item's options menu minus
  what the buttons already do). Albums and playlists list tracks;
  Left/Right in the list jumps to the buttons, Down returns to the same
  track. Artists show rows **Albums**, **Appears on** (a library
  artist's: the albums it appears on without being their album artist,
  e.g. compilations, from its library tracks), **Discography** (a library
  artist's whole catalog, albums already shown above included: MA's
  MusicBrainz discography where MA has it, else the albums of the
  artist's link to the user's own streaming service; an entry MA only
  knows from MusicBrainz is found on the user's services when opened,
  or the page says "Not available on any of your music services."),
  **Top tracks**, **Similar artists** (empty rows hidden); the focused
  row stays the top one, the next showing cut off below it. An artist
  with no rows at all: "Music Assistant has no top tracks, albums, or
  similar artists for <name>."
- **Track page** (Detail for a track: OK on a track anywhere, a track
  row in an album's or playlist's list included): TRACK, the title,
  artists · album, then its length and source ("3:32 · Example Music").
  Buttons **Play** (the track itself, played now; what was queued after
  still follows), **Add to queue**, **Endless mix**, **Favorite**,
  **More** (Play next, Play album from here (its album, in the album's
  order, from this track), Play playlist from here (only when opened
  from a playlist's page: that playlist, in the order and shuffle it
  showed, from this track; MA doesn't record the playlist a track was
  played from, so from Recently played or Search there's none), Remove
  from Recently played when it's there, View artist, View album). Its
  album is always the track's own (MA's track.album), whichever list it
  was opened from. Rows **Album** (its album's card) and **Artists** (a
  card each), each only when it has one; OK opens them, Play/Pause plays
  the focused card.
- **Now Playing:** art, status (PAUSED, LOADING, NOTHING PLAYING, CAN'T
  PLAY THIS TRACK, QUEUE ENDED), title, artist, album, progress (with
  the stream's quality centered between the times: the source's format
  from MA's stream details, "→ FLAC" when the Roku receives another),
  up next.
  QUEUE ENDED: the last track finished with nothing enqueued; it stays
  shown, Play plays it again (by its queue item id), Prev and Next play
  the queue items before and after it (by the queue position MA gave it
  while it was current; else MA's own previous and next), and Lyrics and
  More stay available. The same goes for the remote's Play, Rewind, and
  Fast Forward holds anywhere. Buttons in
  two rows, Up/Down between them (aimed at the nearest button; Up from
  the first goes on to the nav bar): Prev, Play/Pause, Next, Shuffle,
  Repeat (all, one), Favorite (a switch, blue when on); then **Queue**
  (opens Queue on top of Now Playing; Back returns),
  **Lyrics** (opens the Lyrics screen; greyed with nothing loaded),
  **More** (the playing track's options: Play album from here (replaces
  the queue with the track's album from this track, which starts the
  track over), Endless mix, View artist, View album;
  greyed while nothing is loading, playing, or paused; found by the
  track's queue item id, so it works while MA's queue lags or lists no
  current item; a track MA's queue doesn't list yet gets the toast
  "Music Assistant hasn't listed this track yet. Try again in a
  moment.";
  each button keeps its place when its label changes). After the
  Settings' "Now Playing screensaver" time without keys (a minute unless
  changed; never when off), while playing or paused: the drifting ambient
  view; any key wakes it (not while another screen, e.g. Lyrics, covers
  Now Playing; coming back to Now Playing starts the wait over, with the
  setting as it is then).
- **Lyrics** (Now Playing's Lyrics button; Back returns): the playing
  track's lyrics from MA (`metadata/get_track_lyrics`, as MA's web UI
  asks: for a library track without lyrics, MA looks them up in its
  providers and lyrics sources such as LRCLIB, and keeps them) over its
  faded cover, the playing bar below
  (which names the track), and centered at the top "LYRICS" (blue) with
  a grey "synchronized" or "no timing info" beside it, and under them,
  in the hint style, "Up/Down: scroll through the lines · OK: play from
  that line" (synced) or "Up/Down: scroll through the lines" (all within
  the header's 110 px, above the lines' window). While MA answers, the
  loading marker is centered. Synced lyrics (MA's lrc_lyrics, which some
  streaming services provide) follow playback: the current line white
  and centered. Up/Down move a blue cursor through the lines (following
  again 5 s after the last key; Up from the first line goes to the nav
  bar); OK plays from the cursor's line. Plain lyrics scroll with
  Up/Down. None: "No lyrics available". The screensaver stays off while
  it shows, paused or not; a new track loads its lyrics.
- **Queue** (a nav bar entry): up to 50 rows from 5 before the current
  track, the playing one marked NOW, and the queue's item count; **OK on
  a row opens its options** (Play now, Play next, Remove from queue,
  View artist, View album, Clear queue; section 10).
- **Settings** (the profile name in the nav bar): two tabs, **Profile**
  and **This TV** (a TabRow like Library's), over the shown tab's rows,
  with a right column. Opening it looks for this TV among MA's players
  again (section 8).
  - **Profile** (this profile's):
    - **Switch profile**: the picker.
    - **Link another profile**: the server screen.
    - **Unlink this profile**: confirms, revokes the link, and drops the
      profile's settings; then the picker, or the server screen if it
      was the last profile.
    - **Server: <address>**: its description gives MA's version and
      schema, and this TV's player ID there or, without one, the player
      provider and app ID MA needs, then "Link a new profile to change
      server."; OK looks the player up again.
    - **Queue collection when playing a track** (a checkbox, per
      profile): when checked, Play/Pause on a track row of an album's or
      playlist's list plays that album or playlist starting with the
      track (the list's hint says "play the album (playlist) from this
      track"); unchecked, the track alone. A Track page's Play, and
      tracks elsewhere (Library's Tracks, Browse, Search, Home), always
      play the track alone.
  - **This TV** (whichever profile is in use):
    - **Now Playing screensaver**: OK steps through after 1, 2, 5, 10,
      or 30 minutes, then off.
    - **Only play streams from this server** (a checkbox, checked by
      default).
    - **Log level** and **Log collector** (debug builds only).
    - **Forget everything**: confirms, then removes the server and every
      linked profile.
    - **Help and support: <site>**: OK opens a panel with where to open
      an issue, the details to include in a report (the version, this
      Roku's lines as in the right column but its name, and the Music
      Assistant version), and the privacy policy's site.
  - **Keys:** it opens on the tab row, on Profile; OK on a tab shows it
    and goes down to its first row; Left/Right on the tabs wrap. Up
    from the first row goes to the tabs, and from the tabs to the nav
    entry above them (Home's); Down from the nav bar lands on the tab
    below its cursor; Back goes from the rows to the tabs, then to the
    nav bar.
  - **The right column:** the focused row's description (on the tabs,
    what the shown tab holds), the logo, and under it the About text:
    version and build, the tagline, then this Roku on four lines (its
    name; its hardware and network; its Roku OS; its TV signal and UI
    resolution).

## 8. Playing and the Now Playing bar

- Starting playback shows the item in the Now Playing bar with "Loading…"
  and a spinner in the time slot until MA's stream arrives. MA may take
  a while to answer the play request (up to 60 s, e.g. gathering an
  artist's tracks); if no stream arrives 20 s after it answers, the
  toast "Music Assistant didn't start playback. Try again?"
- Mass TV finds this TV among MA's players (a Roku provider player with
  one of the TV's IP addresses, else its name) when a profile becomes
  active, when Settings opens, and when a play has no player to go to or
  MA refuses one. A play with no player waits for that look: if MA lists
  the TV, it is sent; if not, the toast "This TV isn't set up as a Music
  Assistant player yet." When a look finds the TV after one didn't, the
  toast "Reconnected to Music Assistant" says so. A player ID MA no longer
  lists is dropped; MA's next stream also teaches it.
- Shuffle on a Detail page is MA's queue shuffle: Play and track picks
  pass it along (MA would otherwise turn it off for albums).
- "Endless mix" is MA's radio mode for an item.

## 9. Profiles and links over time

- Links last a year; Mass TV replaces each one with a fresh link within
  60 days of expiry (at start and daily, every stored profile). A failed
  renewal warns only under 30 days ("<name>'s link expires in N days.
  Link the profile again in Settings.").
- An expired link: when its profile becomes active, the toast "This
  profile's link has expired. Link it again in Settings."; on the
  picker, "(link expired)" (section 3). A link MA refuses (revoked)
  leaves Home saying "This profile's link is no longer valid. Link it
  again in Settings."

## 10. Keys and menus

| Key | Where | Does |
|---|---|---|
| OK | lists, grids | open an item (a track: its Track page) |
| Play/Pause (tap) | anywhere | on an item focused in a list, grid, or row, with the cursor moved in the last 60 s: play it (on the playing track or its album's card: toggle); otherwise toggle playback, or start MA's queue with nothing loaded (acts on release) |
| Play/Pause (hold, 0.6 s) | anywhere | Now Playing, pushed over the current screen: Back returns there, focus as it was; on Lyrics, back to Now Playing; on Now Playing, nothing |
| Rewind / Fast forward (tap) | Now Playing, and screens without a focused list | seek 10 s (lists use them to page) |
| Rewind / Fast forward (hold) | same | previous / next track |
| Instant replay | anywhere | back 10 s |
| Back | anywhere | up one level (a screen's levels, the nav bar, Home's entry); exit dialog on Home's entry |

- **Mass TV doesn't use the Options (\*) key.** Roku OS takes it for its
  own panel whenever media plays, so every menu has an on-screen route.
- **Item options** (the **More** button on a Detail page, and on Now
  Playing for the playing track): Play now, Play next, Add to queue,
  Shuffle, Play album from here, Play playlist from here (a track, as on
  its Track page), Endless mix, Add to / Remove from
  favorites, Remove from Recently played (a Detail page whose item is
  among Home's "Recently played", looked up when the page opens: MA's
  `music/mark_unplayed` with the entry as logged, which also takes one
  off its play count; Home's row reloads), View artist, View album,
  View description (artists and albums with one: the whole text in a
  panel sized to it, scrolling with Up/Down when taller than the screen
  allows; Close or Back closes it), as they apply and not repeating the
  page's buttons. Items in grids and lists get their options through
  their Detail page, a track through its Track page.
- **Queue item options** (OK on a queue row): Play now, Play next, Remove
  from queue, View artist, View album (as the row's track has them; they
  open the Detail page above the queue, and Back returns to the row),
  Clear queue (empties MA's queue and stops playback, as MA's web UI
  does). Play next and Remove from queue aren't offered on the playing
  row or the next one once MA has handed it to the Roku (MA's queue
  `index_in_buffer`): MA ignores removing and refuses moving those. After
  a change the list is read again as soon as MA answers.
- Both are Mass TV menus (OptionsMenu, titled with the item's name): OK
  picks and closes, Back closes, and focus returns to where it was. If
  its screen is covered or removed meanwhile, the menu goes with it.
