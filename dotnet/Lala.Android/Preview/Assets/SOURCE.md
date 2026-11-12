# 手機預覽視覺素材

依使用者提供的五張介面參考圖製作。使用內建 image_gen 產生獨立美術素材；所有互動介面由 Avalonia 程式碼繪製，沒有把參考截圖當作整頁介面。這些均非官方遊戲圖資。

- castle-header.png：城堡夜空橫幅。
- lala-mascot.png：透明角色立繪；頭像於顯示時取景。
- town-preview.png：城鎮示意地圖，不作為導航或碰撞資料。
- item-atlas.png：4 欄 × 6 列道具示意圖集；畫面依格子顯示。

## 產生提示詞

後續聊天、夥伴與工具頁新增的頭像及插畫見 [FEATURES_SOURCE.md](FEATURES_SOURCE.md)。

### castle-header.png

Use case: stylized-concept. Asset type: panoramic mobile game dashboard header background, no text. Reference image is the visual direction only; create artwork, not a screenshot or full UI. A dark midnight-blue fantasy sky, subtle stars and wisps of clouds. At far right 75% width a luminous small floating gothic castle with a bright cyan central spire, concentric thin cyan magical arcs behind it, trailing blue clouds. Left 65% nearly black/navy negative space for a separately overlaid character and title, extremely dark blue not blank white. Premium polished anime fantasy game illustration, restrained cyan glow. Wide landscape 3:1 banner. No typography, no logos, no interface panels, no buttons, no character. Save the generated project asset as an image file.

### lala-mascot.png

Use case: stylized-concept. Asset type: character mascot cutout for an Android fantasy game header and circular avatar. Reference is style direction only. A cheerful chibi anime fantasy girl, head and shoulders with both hands visible at bottom, golden blonde fluffy twin-tail hair tied with pink ribbons, small cream-white and pink flowers in her hair, large amber eyes, gentle smile, pink and purple fantasy dress and tiny gold pendant. Face front, centered full upper body, no cropping of hair or hands, warm beautifully shaded 2D Japanese mobile RPG illustration matching the reference. Crisp high quality line art, soft luminous coloring. Transparent background, no border, no text, no icons, no scenery.

### town-preview.png

Use case: stylized-concept. Asset type: square top-down minimap artwork for a fantasy RPG interface. Reference image is only art direction. Create a clean detailed top-down 2D JRPG medieval town square, blue slate tile roofs on stone half timbered buildings along left and right, cobbled plaza center, circular blue stone fountain exactly at center, greenery and flower planters and small striped vendor stalls. Broad clear walkways lead north, south, east, west. Twilight blue lighting, soft warm window lights, polished hand painted videogame environment art. Entire square fills image edge to edge. NO UI elements, no map markers, no arrows, no coordinate labels, no route lines, no text, no compass, no people. These overlays will be drawn separately by code.

### item-atlas.png

Use case: stylized-concept. Asset type: RPG inventory ICON ATLAS, one square PNG sheet, exactly 4 columns by 6 rows of equal sized cells, edge to edge, all24 icons centered in their own cell. Deep solid dark navy #07172c background in every cell, no dividing lines. Polished 2D fantasy RPG item illustrations with colorful magical lighting, readable silhouettes. Each object occupies about 75% of its cell, consistent padding. Row1: pink heart health potion in ornate gold glass bottle; cyan eight-point magic crystal; ornate golden key; rolled parchment magic scroll with purple seal. Row2: purple ringed glowing orb; cobalt blue glass potion; emerald green potion; little orange campfire with logs. Row3: silver white feather; clear blue pearl orb; silver iron ore chunks; cut brown wooden log. Row4: white chamomile herb sprig; blue luminous mushroom; sharp blue crystal shard; brown animal leather. Row5: bright red apple; golden bread loaf; small cloth bowl of rice; iron pickaxe. Row6: simple wood fishing rod; clear blue water bottle; coiled beige rope; flaming wooden torch. EXACT ordered grid. NO text, NO numbers, no labels, no UI borders, no frames. Four columns and six rows must be spatially evenly divided for native rendering of individual cells.
