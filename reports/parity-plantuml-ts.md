# Parity: plantuml-ts

Pin: `97a5992201a7b1bc5d4063a81da609fe7387fede`

| family | blocks | fr | fa | disagree | timeout | diagram_mismatch | raw_fr | FR rate |
|---|---|---|---|---|---|---|---|---|
| activity-legacy | 119 | 0 | 0 | 0 | 2 | 1 | 0 | 0.00% |
| activity3 | 777 | 0 | 2 | 3 | 8 | 1 | 33 | 0.00% |
| board-files-git | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.00% |
| class | 1166 | 0 | 14 | 1 | 3 | 25 | 30 | 0.00% |
| common (overlay) | 4401 | 8 | 49 | 0 | 0 | 488 | 184 | 0.19% |
| description | 662 | 0 | 6 | 0 | 9 | 0 | 52 | 0.00% |
| gantt | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.00% |
| json | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.00% |
| meta-diagrams | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.00% |
| mindmap-wbs | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.00% |
| misc-charts | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.00% |
| nwdiag-packet | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.00% |
| salt | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.00% |
| sequence | 1223 | 0 | 3 | 0 | 4 | 0 | 52 | 0.00% |
| single-line | 3 | 0 | 0 | 0 | 0 | 2 | 0 | 0.00% |
| state | 300 | 0 | 4 | 0 | 2 | 0 | 3 | 0.00% |
| style (overlay) | 428 | 3 | 0 | 0 | 0 | 85 | 11 | 0.70% |
| timing | 65 | 0 | 3 | 0 | 0 | 0 | 0 | 0.00% |
| unclassified | 86 | 0 | 0 | 12 | 3 | 0 | 0 | 0.00% |
| **total** | 4401 | 0 | 32 | 16 | 31 | 29 | 170 | 0.00% |

## Cases

- activity-legacy: `class/lobosa-57-gozi031.puml#0` timeout (unclassified)
- activity-legacy: `class/pudixe-16-deki169.puml#0` timeout (bug) - Lark timeout only: parses and agrees in 27 s CPU (baseline grammar 19 s); no interpreter/Lark disagreement
- activity3: `activity/boxoto-53-sifo232.puml#0` timeout (unclassified)
- activity3: `activity/gacaja-15-keko600.puml#0` timeout (unclassified)
- activity3: `activity/judatu-15-xize591.puml#0` timeout (bug) - Lark timeout only, under load: 23.1 s without T21b, 21.3 s with; the interpreter agrees with the jar
- activity3: `activity/juleki-83-xusi470.puml#0` disagree (bug) - Lark only: a 14-line `if (` header (DecoratorMultine join); Lark approximates join as one line (tools/emit/lark.py docstring)
- activity3: `activity/kotiso-16-vizi552.puml#0` timeout (unclassified)
- activity3: `activity/labala-74-juki864.puml#0` timeout (unclassified)
- activity3: `activity/lopone-15-xiki477.puml#0` disagree (unclassified)
- activity3: `activity/xabesu-51-dimi831.puml#0` disagree (unclassified)
- activity3: `class/bofaxe-86-mizu331.puml#0` timeout (bug) - Lark timeout only, under load: 50.5 s without T21b, 51.0 s with; the interpreter agrees with the jar
- activity3: `class/duluve-89-mati167.puml#0` fa (semantic) - unknown arrow color `-[#toto]->`: NoSuchColorException at execution (gap/arrow-unknown-color)
- activity3: `class/finadu-74-duvi890.puml#0` timeout (bug) - Lark timeout only: `<style>` block, the known style/common Lark cost (.agent-notes/fix-emit-top.md)
- activity3: `class/leseku-63-ruda113.puml#0` fa (semantic) - unknown stereotype color `<<#zzblue>>`: NoSuchColorException at execution (gap/activity-unknown-color)
- activity3: `class/pojanu-14-koka953.puml#0` timeout (bug) - Lark timeout only: one 2.4 kB base64 image line; also times out with the generated model alone
- class: `class/dulone-62-neri182.puml#0` fa (semantic) - map CapitalCity defined twice: "Map already exists"
- class: `class/fegafi-82-xiri255.puml#0` fa (semantic) - class X.Encoding made X a package; `class X` then fails: "Bad name"
- class: `class/foxufo-19-nuco936.puml#0` fa (semantic) - package Order exists, `class Order` fails: "Bad name"
- class: `class/gutute-00-gaki684.puml#0` timeout (unclassified)
- class: `class/jicogu-02-cani636.puml#0` fa (semantic) - Order exists as a package; class Order {...} cannot mute it: "Cannot create Order because it already exists"
- class: `class/luzive-62-zote562.puml#0` fa (semantic) - `<> StationCrossing` reuses a class name: "Already existing"
- class: `class/neruke-07-ruce381.puml#0` disagree (unclassified)
- class: `class/notevi-43-sita948.puml#0` fa (semantic) - Order exists as a package; class Order {...}: "Cannot create Order because it already exists"
- class: `class/pedoze-30-xoxo765.puml#0` fa (semantic) - class X then class X.Encoding: "Bad hierarchy for class"
- class: `class/petiku-70-fogu777.puml#0` fa (semantic) - bar created by a link, `struct bar {` cannot mute it: "Cannot create bar because it already exists"
- class: `class/pizegi-06-jiro383.puml#0` fa (semantic) - lollipop link to a class that does not exist: "No class"
- class: `class/revosa-68-goci965.puml#0` fa (semantic) - b is a class, so `b.b` in a link cannot resolve it as a package: "Not a package"
- class: `class/rogoxa-80-mori838.puml#0` fa (semantic) - package Toto exists, `class Toto` fails: "Bad name"
- class: `class/sunuli-13-geju490.puml#0` fa (semantic) - class com.Toto then class com.Toto.Internal: "Bad hierarchy for class"
- class: `class/xadepe-11-noja686.puml#0` fa (semantic) - Toto is a class, `class Toto.Internal` needs it as a package: "Not a package"
- class: `object/losote-76-beki147.puml#0` fa (semantic) - object user defined twice: "Object already exists"
- class: `sequence/zakuta-81-pese010.puml#0` timeout (unclassified)
- class: `sequence/zosaxa-86-mora157.puml#0` timeout (unclassified)
- description: `class/cukafa-49-fona812.puml#0` timeout (bug) - Lark timeout only, near the budget under shared load; 6 other blocks time out only with the pre-T19 grammar
- description: `class/foraba-98-sagi735.puml#0` timeout (bug) - Lark timeout only; times out with the pre-T19 grammar too
- description: `class/gikaju-64-bari602.puml#0` fa (semantic) - C4 Rel() links someContainer before `rectangle ... as someContainer` declares it: "This element (someContainer) is already defined" (the link made it STILL_UNKNOWN)
- description: `class/josimu-04-silu988.puml#0` timeout (bug) - Lark timeout only; times out with the pre-T19 grammar too
- description: `class/mucajo-31-lifo004.puml#0` fa (semantic) - Provider is a group after `component [Provider] {`; the later `[Provider]` fails: "This element (Provider) is already defined"
- description: `class/nixuje-20-bobu879.puml#0` fa (semantic) - `sprite ... jar:archimate/strategy-value-stream` names no internal sprite: "No such internal sprite" (runtime resource table)
- description: `class/refabu-21-jesu466.puml#0` timeout (bug) - Lark disagreement only: `title ` (trailing blank) then `end title`; the Lark emitter puts no `_WS?` before `_NL` after a multiline first line (queued in reports/queued-shared-changes.md). Hidden before T19 because the bare word `title` also parsed as an element
- description: `class/ropexu-72-jecu171.puml#0` timeout (bug) - Lark timeout only; times out with the pre-T19 grammar too
- description: `class/xexuza-21-kifa053.puml#0` fa (semantic) - `note left of compo` before compo exists: "Not known: compo"
- description: `class/xigele-78-sija109.puml#0` timeout (bug) - Lark timeout only; times out with the pre-T19 grammar too
- description: `component/reroca-56-safi108.puml#0` timeout (bug) - Lark timeout only; times out with the pre-T19 grammar too
- description: `component/sabafe-32-viju467.puml#0` fa (semantic) - a second `note as _n` (in another package) reuses the existing note code: "Note already created: _n"
- description: `sequence/taneno-85-fatu449.puml#0` timeout (bug) - Lark timeout only; times out with the pre-T19 grammar too
- description: `sequence/xusuxe-62-guba767.puml#0` timeout (bug) - Lark timeout only; times out with the pre-T19 grammar too
- description: `usecase/nekote-79-pori818.puml#0` fa (semantic) - `usecase sameid` then `rectangle sameid`: "This element (sameid) is already defined"
- sequence: `class/rujudi-37-nelu670.puml#0` timeout (unclassified)
- sequence: `sequence/moragi-03-luto111.puml#0` fa (semantic) - preprocessor error: %dirpath() has arity 0, called with one argument; not a sequence command
- sequence: `sequence/riguga-63-mujo058.puml#0` fa (semantic) - create then a message to another participant: SequenceDiagram.addMessage pendingCreate check (state, gap/create-then-other-message)
- sequence: `sequence/sosudi-70-jape391.puml#0` fa (semantic) - activate/deactivate just after a delay: SequenceDiagram.activate lastDelay check (state, gap/activate-after-delay)
- sequence: `sequence/tatesu-03-zozo948.puml#0` timeout (unclassified)
- sequence: `sequence/tumuke-16-xomo243.puml#0` timeout (unclassified)
- sequence: `sequence/vitusu-66-boxa381.puml#0` timeout (unclassified)
- state: `class/fugedo-34-fice721.puml#0` fa (semantic) - link endpoint ChildMode1.A resolves under the current group, whose parent state does not exist (cross-line, gap/link-unknown-parent)
- state: `class/somuke-94-buzi673.puml#0` timeout (bug) - Lark timeout only: `!theme plain` expansion (~160 lines); 15 s before T20, parses and agrees given 60 s
- state: `class/sugico-41-vase848.puml#0` timeout (bug) - Lark timeout only: `!theme plain` expansion (~160 lines); 17 s before T20, parses and agrees given 60 s
- state: `class/xacona-99-peze211.puml#0` fa (semantic) - link endpoint pUndetected belongs to a concurrent region and is used outside it (cross-line, gap/state-reused-in-other-region)
- state: `class/zecivu-62-pagu681.puml#0` fa (semantic) - link endpoint XA13 is declared later inside a concurrent region; links run in pass TWO and cannot use it at the root (cross-line)
- state: `sequence/cagego-53-vemo516.puml#0` fa (semantic) - link endpoint c belongs to another concurrent region (cross-line, gap/state-reused-in-other-region)
- timing: `class/sezuvo-55-nose464.puml#0` fa (semantic) - constraint on an undeclared player: CommandConstraint looks PART1 up in the player table (gap/constraint-unknown-player)
- timing: `class/tobafo-52-libo419.puml#0` fa (semantic) - constraint to an undefined time label: TimeTickBuilder resolves :code in the label table, null fails (gap/constraint-unknown-label)
- timing: `sequence/pebecu-20-deci596.puml#0` fa (semantic) - message to an undeclared player: CommandTimeMessage looks PART2 up in the player table (gap/message-unknown-player)
- unclassified: `activity/gabeme-89-tiko230.puml#0` disagree (unclassified)
- unclassified: `activity/jokaxi-40-toko207.puml#0` disagree (unclassified)
- unclassified: `activity/kedozi-45-begu156.puml#0` disagree (unclassified)
- unclassified: `activity/nakavu-98-pela661.puml#0` disagree (unclassified)
- unclassified: `activity/pejima-95-nuxu520.puml#0` disagree (unclassified)
- unclassified: `activity/veducu-71-tika634.puml#0` disagree (unclassified)
- unclassified: `activity/velodu-59-sada437.puml#0` disagree (unclassified)
- unclassified: `activity/vipixe-71-rika369.puml#0` timeout (unclassified)
- unclassified: `activity/xoreni-54-xoro817.puml#0` disagree (unclassified)
- unclassified: `class/kepife-84-jigi755.puml#0` disagree (unclassified)
- unclassified: `class/kipive-74-lele070.puml#0` timeout (unclassified)
- unclassified: `class/rubife-18-nege510.puml#0` disagree (unclassified)
- unclassified: `class/zalulo-78-voma912.puml#0` disagree (unclassified)
- unclassified: `class/zinano-86-zeke427.puml#0` disagree (unclassified)
- unclassified: `sequence/pajude-35-jisu021.puml#0` timeout (unclassified)
