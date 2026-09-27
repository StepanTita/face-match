# Demo data

Real photos of three actors, sourced entirely from [Wikimedia
Commons](https://commons.wikimedia.org) under licenses that permit
redistribution (CC BY, CC BY-SA, or public domain), used to demonstrate
`facematch find` and `facematch group` end-to-end against genuinely varied
photo quality, lighting, angle, and era — not the project maintainer's own
photos, and not scraped from anywhere that would make redistribution here a
copyright problem.

See the [main README](../README.md#demo) for the demo write-up and results.
Full per-photo credit is in [`attributions.json`](attributions.json) and the
table below — every image here must be attributed under its license when
reused; do not strip this file out of a derived copy of this data.

## Layout

- `references/` — 4 photos of Tom Hiddleston, used to build the `find`
  reference embeddings.
- `archive/` — the "messy archive" `find` and `group` scan: 5 more Hiddleston
  photos (the real matches `find` should discover), plus 6 Chris Evans and 7
  Emma Watson photos (true negatives for `find`, and the other two people
  `group` needs to cluster separately).
- `results/` — the actual, unedited output of running both commands against
  the above (see the main README's Demo section for the full results).

## Why these three

All three have a large body of press/convention photography on Commons
released under CC licenses by photographers who systematically license their
work that way (e.g. Gage Skidmore), which made it possible to assemble a real
spread of *quality* (phone-era stills next to fansite Flickr grabs down to a
184x262 crop), *lighting* (red carpets, panels, outdoor press events),
*angle*, and *era* (roughly 2010-2025) for the same three people — the exact
conditions a real personal photo archive has, without needing anyone's
personal photos to prove the tool works.

## Full attribution

| File | Photographer | License | Source |
| --- | --- | --- | --- |
| `archive/evans/evans_01.jpg` | File:Chris Evans at WonderCon 2010 1.JPG: BrokenSphere derivative work: Minerva97 | CC BY-SA 3.0 | [Commons](https://commons.wikimedia.org/wiki/File%3AChris_Evans_-_The_Losers_film_panel_-_WonderCon_2010.jpg) |
| `archive/evans/evans_04.jpg` | Gage Skidmore | CC BY-SA 3.0 | [Commons](https://commons.wikimedia.org/wiki/File%3AChris_Evans_by_Gage_Skidmore.jpg) |
| `archive/evans/evans_05.jpg` | Chairman of the Joint Chiefs of Staff from Washington D.C, United States | CC BY 2.0 | [Commons](https://commons.wikimedia.org/wiki/File%3AChris_Evans_in_Dec_6%2C_2016.jpg) |
| `archive/evans/evans_06.jpg` | United States House of Representatives - Office of Don Young | Public domain | [Commons](https://commons.wikimedia.org/wiki/File%3AChris_Evans_in_2019.jpg) |
| `archive/evans/evans_07.jpg` | Tony Cárdenas | Public domain | [Commons](https://commons.wikimedia.org/wiki/File%3AChris_Evans_2020_%28cropped%29.jpg) |
| `archive/evans/evans_09.jpg` | Sara Komatsu | CC BY-SA 4.0 | [Commons](https://commons.wikimedia.org/wiki/File%3AChris_Evans_at_the_2025_Toronto_International_Film_Festival_%28cropped%29.jpg) |
| `archive/hiddleston/hiddleston_07.jpg` | Gage Skidmore from Peoria, AZ, United States of America | CC BY-SA 2.0 | [Commons](https://commons.wikimedia.org/wiki/File%3ATom_Hiddleston_%2827992871594%29.jpg) |
| `archive/hiddleston/hiddleston_08.jpg` | Gage Skidmore from Peoria, AZ, United States of America | CC BY-SA 2.0 | [Commons](https://commons.wikimedia.org/wiki/File%3ATom_Hiddleston_%2848468924186%29.jpg) |
| `archive/hiddleston/hiddleston_09.jpg` | Gage Skidmore from Peoria, AZ, United States of America | CC BY-SA 2.0 | [Commons](https://commons.wikimedia.org/wiki/File%3ATom_Hiddleston_%2848468934866%29.jpg) |
| `archive/hiddleston/hiddleston_10.jpg` | Gage Skidmore from Peoria, AZ, United States of America | CC BY-SA 2.0 | [Commons](https://commons.wikimedia.org/wiki/File%3ATom_Hiddleston_%2848468955071%29.jpg) |
| `archive/hiddleston/hiddleston_11.jpg` | Gage Skidmore from Peoria, AZ, United States of America | CC BY-SA 2.0 | [Commons](https://commons.wikimedia.org/wiki/File%3ATom_Hiddleston_%2848468962561%29_%28cropped%29.jpg) |
| `references/hiddleston/hiddleston_01.jpg` | Sachyn Mital | CC BY-SA 3.0 | [Commons](https://commons.wikimedia.org/wiki/File%3ATom_Hiddleston_%28Avengers_Red_Carpet%29.jpg) |
| `references/hiddleston/hiddleston_02.jpg` | Mango Films (Manjinder Virk) | CC BY 3.0 | [Commons](https://commons.wikimedia.org/wiki/File%3ATom_Hiddleston_Out_of_Darkness.jpg) |
| `references/hiddleston/hiddleston_05.jpg` | Sue Lukenbaugh from Sacramento, USA | CC BY-SA 2.0 | [Commons](https://commons.wikimedia.org/wiki/File%3ATom_Hiddleston_%289404809849%29.jpg) |
| `references/hiddleston/hiddleston_06.jpg` | Mark Jenkinson @therealmarky | CC BY-SA 2.0 | [Commons](https://commons.wikimedia.org/wiki/File%3ATom_Hiddleston_Jaguar_ad_February_2014.jpg) |
| `archive/watson/watson_01.jpg` | EmmaWatsonNov2010.jpg: Joella Marano at https://www.flickr.com/photos/ellasportfolio/ derivative work: Bff (talk) | CC BY 2.0 | [Commons](https://commons.wikimedia.org/wiki/File%3AEmmaWatsonNov2010-2.jpg) |
| `archive/watson/watson_02.jpg` | David Shankbone | CC BY 3.0 | [Commons](https://commons.wikimedia.org/wiki/File%3AEmma_Watson_2012_Shankbone_%28cropped%29.JPG) |
| `archive/watson/watson_03.jpg` | David Shankbone | CC BY 2.0 | [Commons](https://commons.wikimedia.org/wiki/File%3AEmma_Watson%2C_2012.jpg) |
| `archive/watson/watson_04.jpg` | Georges Biard | CC BY-SA 3.0 | [Commons](https://commons.wikimedia.org/wiki/File%3AEmma_Watson_2%2C_2013.jpg) |
| `archive/watson/watson_06.jpg` | Emma Watson GoF Premiere.jpg: Zaheer12a derivative work: Lošmi (talk) | CC BY-SA 3.0 | [Commons](https://commons.wikimedia.org/wiki/File%3AEmma_Watson_GoF_Premiere_Crop.jpg) |
| `archive/watson/watson_07.jpg` | Mars Films | CC BY 3.0 | [Commons](https://commons.wikimedia.org/wiki/File%3AEmma_Watson_interview_in_2017_%28cropped%29.jpg) |
| `archive/watson/watson_08.jpg` | ONU Brasil | CC BY 3.0 | [Commons](https://commons.wikimedia.org/wiki/File%3AEmma_Watson_ONU_2017.jpg) |
