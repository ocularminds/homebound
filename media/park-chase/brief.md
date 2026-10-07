# A little hare-raising afternoon

An original, family-friendly 3D cartoon for the HomeBound FireTV canvas.

## Story and continuity

A couple relaxes under a broad tree in a lively city park. Children play nearby,
and a local train arrives behind them. Passengers step onto the platform. A
cream-colored rabbit with long pink ears tumbles from a low branch, landing
unhurt beside a stocky cinnamon-and-cream bulldog with a blue collar. The rabbit
bolts. A ridiculous, windblown chase follows through the park and past the
station. Leaves, ears and the bulldog's jowls fly in the breeze.

The chase reaches a large, cozy living room. Two parents and two children are
watching television and sharing popcorn. The rabbit slips under the dining
table. The bulldog slides to a halt with a comic tire-screech sound. The children
jump up in surprise, scattering popcorn. The rabbit gives the panting bulldog a
cheeky sideways look from beneath the table. Nobody is hurt.

## Edit

| Program time | Shot | Action and sound |
| --- | --- | --- |
| 00:00-00:10 | Park wide | Couple under the tree, children playing, soft music and birds. |
| 00:10-00:15 | Station | Passengers step down from the local train onto the platform. |
| 00:15-00:20 | Unexpected visitor | Rabbit falls from a low branch and bounces safely; bulldog reacts. Slide whistle and boing. |
| 00:20-00:30 | The chase | Rabbit hops away, bulldog gives chase. Pattering feet and jaunty music. |
| 00:30-00:35 | A windy shortcut | Swirling leaves and flapping ears as the animals reach the open doorway. Wind and whooshes. |
| 00:35-00:45 | Movie night | Cozy living room, family watching TV and eating popcorn. Warm lighting and a slower pace. |
| 00:45-00:50 | Uninvited guests | Bulldog charges in and skids beside the rabbit. Tire screech at 00:47.250. |
| 00:50-00:55 | Popcorn everywhere | Two children leap up and popcorn flies. Surprised gasps and panting. |
| 00:55-01:00 | Last laugh | Low camera under the table; rabbit peeks and smirks at the panting dog. Playful final cadence. |

Two original six-second house promos interrupt playback at program times
00:20 and 00:42. They are labeled as demo commercials. The program's own video
file contains no ads; the player pauses it, plays the separate commercial, and
resumes the exact paused position. The ambient canvas receives break/program
signals for the current playback session.

Eligible FireTV notes appear beside the commercial, with a calm card treatment
and enough space to read. Compose both promos with the main subject and copy
toward the left and leave the right third quiet. Notes disappear as soon as the
program resumes. Personal-note delivery still requires a fresh, matching
audience with no guests. Pausing a commercial also pauses its countdown, giving
the viewer time to read; the cartoon remains at the saved playhead.

## Visual and audio treatment

16:9, 24 frames per second. Rounded, expressive 3D characters and a warm toy-like
material finish. Soft shadows, a mint-and-gold park, coral train, cream rabbit,
cinnamon bulldog, amber lamps and teal living-room furniture. Camera cuts and
tracking shots serve the action; this is animation, not a slideshow.

The animation and sound were generated through the user's connected Runway
account, using character and scene references for continuity. No
copyrighted characters, third-party films or ads, or real product claims. No
dialogue is required; comic action and sound carry the story.

## Production and playback

Completed on 2026-10-07. Runway Gen-4 Turbo supplied the animation, Nano Banana
Pro supplied reference images, and Lyria 3 Pro supplied the original score.
Runway also generated the six sound-effect layers. The
[production manifest](production.json) records the selected source task IDs,
submitted prompts, edit timing, audio cues, and SHA-256 checksums.

The quiet family shot uses half-speed playback; the braking shot uses its clean
first five seconds. Children and rabbit reactions have separate close shots.
Each commercial holds its last frame for approximately one second, with exact
HomeBound typography added during editing. Live notes remain separate from the
video. Source selections were reviewed for character continuity and extra
figures before export.

The finished 60-second program and two six-second commercials are 1280×720,
24 fps H.264/AAC MP4 files in `app/web/static/media/`, accompanied by a poster
and English sound captions. They play through the browser's video element with
HTTP byte-range support. The deployed web app does not require Runway access or
a rendering service. Open [the cartoon on the FireTV canvas](http://127.0.0.1:8300/tv?play=park_chase).
