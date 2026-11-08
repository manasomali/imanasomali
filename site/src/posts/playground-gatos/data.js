// Numbers of the cat wall playground plan. Everything is in cm. The text that goes with them
// is in copy.js; numbers are formatted per language (decimal comma in Portuguese).

// Cutting plan of the 220 x 160 cm sheet: [x, y, width, height, kind, label], measured from
// the sheet's top-left corner. Gaps of 0.6 between pieces are the blade kerf. `label` is a
// key of copy.<lang>.diagrams.plan.pieces (null: small pieces left unlabeled).
export const SHEET = { width: 220, height: 160 };

export const sheetPieces = [
  [0, 0, 39.5, 30, 'house', 'house30'],
  [40.1, 0, 39.5, 30, 'house', 'house30'],
  [80.2, 0, 39.5, 30, 'house', 'house30'],
  [120.3, 0, 39.5, 30, 'house', 'house30'],
  [160.4, 0, 30, 23, 'top', 'topM'],
  [160.4, 23.6, 30, 6.4, 'waste', null],
  [191, 0, 27, 27, 'house', 'side'],
  [191, 27.6, 27, 2.4, 'waste', null],
  [0, 30.6, 39.5, 27, 'house', 'house27'],
  [40.1, 30.6, 39.5, 27, 'house', 'house27'],
  [80.2, 30.6, 39.5, 27, 'house', 'house27'],
  [120.3, 30.6, 39.5, 27, 'house', 'house27'],
  [160.4, 30.6, 30, 23, 'top', 'topM'],
  [160.4, 54.2, 30, 3.4, 'waste', null],
  [191, 30.6, 27, 27, 'house', 'side'],
  [0, 58.2, 60, 28, 'top', 'topL'],
  [60.6, 58.2, 60, 28, 'top', 'topL'],
  [121.2, 58.2, 60, 28, 'top', 'topL'],
  [181.8, 58.2, 36, 3, 'house', 'spacer'],
  [181.8, 61.8, 36, 3, 'house', 'spacer'],
  [181.8, 65.4, 30, 7, 'back', 'spareM'],
  [181.8, 73, 10, 7, 'back', 'spareS'],
  [192.4, 73, 10, 7, 'back', 'spareS'],
  [203, 73, 10, 7, 'back', 'spareS'],
  [181.8, 80.6, 36, 3, 'house', 'spareSpacer'],
  [0, 86.8, 30, 23, 'top', 'topM'],
  [30.6, 86.8, 30, 23, 'top', 'topM'],
  [61.2, 86.8, 30, 23, 'top', 'topM'],
  [91.8, 86.8, 10, 23, 'top', 'S'],
  [102.4, 86.8, 10, 23, 'top', 'S'],
  [113, 86.8, 10, 23, 'top', 'S'],
  [123.6, 86.8, 10, 23, 'top', 'S'],
  [134.2, 86.8, 10, 23, 'top', 'S'],
  [144.8, 86.8, 10, 23, 'top', 'S'],
  [155.4, 86.8, 60, 7, 'back', 'backL'],
  [155.4, 94.4, 60, 7, 'back', 'backL'],
  [155.4, 102, 60, 7, 'back', 'backL'],
  [0, 110.4, 30, 7, 'back', 'backM'],
  [30.6, 110.4, 30, 7, 'back', 'backM'],
  [61.2, 110.4, 30, 7, 'back', 'backM'],
  [91.8, 110.4, 30, 7, 'back', 'backM'],
  [122.4, 110.4, 30, 7, 'back', 'backM'],
  [153, 110.4, 10, 7, 'back', 'S'],
  [163.6, 110.4, 10, 7, 'back', 'S'],
  [174.2, 110.4, 10, 7, 'back', 'S'],
  [184.8, 110.4, 10, 7, 'back', 'S'],
  [195.4, 110.4, 10, 7, 'back', 'S'],
  [206, 110.4, 10, 7, 'back', 'S'],
  [0, 118, 60, 3.5, 'cleat', 'cleatL'],
  [60.6, 118, 60, 3.5, 'cleat', 'cleatL'],
  [121.2, 118, 60, 3.5, 'cleat', 'cleatL'],
  [181.8, 118, 30, 3.5, 'cleat', 'cleatM'],
  [0, 122.1, 39.5, 3.5, 'cleat', 'cleatHouse'],
  [40.1, 122.1, 39.5, 3.5, 'cleat', 'cleatHouse'],
  [80.2, 122.1, 30, 3.5, 'cleat', 'cleatM'],
  [110.8, 122.1, 30, 3.5, 'cleat', 'cleatM'],
  [141.4, 122.1, 30, 3.5, 'cleat', 'cleatM'],
  [172, 122.1, 30, 3.5, 'cleat', 'cleatM'],
  [0, 126.2, 10, 3.5, 'cleat', null],
  [10.6, 126.2, 10, 3.5, 'cleat', null],
  [21.2, 126.2, 10, 3.5, 'cleat', null],
  [31.8, 126.2, 10, 3.5, 'cleat', null],
  [42.4, 126.2, 10, 3.5, 'cleat', null],
  [53, 126.2, 10, 3.5, 'cleat', null],
  [63.6, 126.2, 60, 3.5, 'cleat', 'spareCleatL'],
  [124.2, 126.2, 30, 3.5, 'cleat', 'spareCleatM'],
  [154.8, 126.2, 39.5, 3.5, 'cleat', 'spareCleatHouse'],
  [194.9, 126.2, 10, 3.5, 'cleat', 'spareS'],
  [205.5, 126.2, 10, 3.5, 'cleat', 'spareS'],
  [0, 130.3, 220, 5, 'rail', 'rail'],
  [0, 135.9, 220, 5, 'rail', 'rail'],
  [0, 141.5, 220, 5, 'rail', 'rail'],
  [0, 147.1, 220, 5, 'rail', 'rail'],
  [0, 152.7, 220, 5, 'rail', 'rail'],
];

// Marks on the long edge that gets the 45° bevel (cleats and rails): [x1, x2, y]
export const chamferMarks = [
  [1, 10.3, 118.9], [49.7, 59, 118.9], [61.6, 70.9, 118.9], [110.3, 119.6, 118.9],
  [122.2, 131.5, 118.9], [170.9, 180.2, 118.9], [182.8, 187.3, 118.9], [206.3, 210.8, 118.9],
  [1, 7, 123], [32.5, 38.5, 123], [41.1, 47.1, 123], [72.6, 78.6, 123], [81.2, 85.7, 123],
  [104.7, 109.2, 123], [111.8, 116.3, 123], [135.3, 139.8, 123], [142.4, 146.9, 123],
  [165.9, 170.4, 123], [173, 177.5, 123], [196.5, 201, 123],
  [1, 9, 127.1], [11.6, 19.6, 127.1], [22.2, 30.2, 127.1], [32.8, 40.8, 127.1],
  [43.4, 51.4, 127.1], [54, 62, 127.1], [64.6, 73.9, 127.1], [113.3, 122.6, 127.1],
  [125.2, 129.7, 127.1], [148.7, 153.2, 127.1], [155.8, 161.8, 127.1], [187.3, 193.3, 127.1],
  [195.9, 203.9, 127.1], [206.5, 214.5, 127.1],
  [1, 35.9, 131.2], [184.1, 219, 131.2], [1, 35.9, 136.8], [184.1, 219, 136.8],
  [1, 35.9, 142.4], [184.1, 219, 142.4], [1, 35.9, 148], [184.1, 219, 148],
  [1, 35.9, 153.6], [184.1, 219, 153.6],
];

// Marks on the left edge of the cutting plan (the 13 rip cuts that matter, plus the sheet edges)
export const planTicks = [0, 30, 57.6, 86.2, 109.8, 117.4, 157.7, 160];

// Cutting sequence, cumulative marks from the same edge (kerf included)
export const ripCuts = [30, 57.6, 86.2, 109.8, 117.4, 121.5, 125.6, 129.7, 135.3, 140.9, 146.5,
  152.1, 157.7];

export const stripCuts = [
  { strip: 'A', cuts: [39.5, 79.6, 119.7, 159.8, 190.4, 218] },
  { strip: 'B', cuts: [39.5, 79.6, 119.7, 159.8, 190.4, 218] },
  { strip: 'C', cuts: [60, 120.6, 181.2] },
  { strip: 'D', cuts: [30, 60.6, 91.2, 101.8, 112.4, 123, 133.6, 144.2, 154.8] },
  { strip: 'E', cuts: [30, 60.6, 91.2, 121.8, 152.4, 163, 173.6, 184.2, 194.8, 205.4, 216] },
];

// Blocks opened in step 3: rips across the block, then the cross-cuts on each strip
// (`crossCuts` groups are separate strips; `eachStrip`: the same cut on every strip)
export const blockCuts = [
  { rips: [7, 14.6, 22.2], crossCuts: [[215.4]], eachStrip: true },
  { rips: [3, 6.6], crossCuts: [[217.8]], eachStrip: true },
  { rips: [14.2, 21.8, 25.4], crossCuts: [[211.8], [191.8, 202.4, 213], [217.8]] },
];

export const bevelZoneCuts = [
  [60, 120.6, 181.2, 211.8],
  [39.5, 79.6, 110.2, 140.8, 171.4, 202],
  [10, 20.6, 31.2, 41.8, 52.4, 63, 123.6, 154.2, 194.3, 204.9, 215.5],
];

// Wall elevation: heights from the floor, x from the wall's left edge
export const WALL = { width: 270, height: 260 };
export const DOOR = { x: 170, width: 100, height: 220 };
export const RAIL_WIDTH = 5;
export const BACK_HEIGHT = 7;
export const THICKNESS = 1.5;
export const rails = [
  { height: 75, length: 170 },
  { height: 114, length: 170 },
  { height: 153, length: 170 },
  { height: 192, length: 170 },
  { height: 230, length: 270 },
];
export const PLATFORM_WIDTH = { L: 60, M: 30, S: 10 };
// [rail height, x, size]
export const platforms = [
  [75, 10, 'L'], [75, 85, 'M'], [75, 130, 'S'],
  [114, 5, 'L'], [114, 80, 'M'], [114, 125, 'S'], [114, 150, 'S'],
  [153, 5, 'M'], [153, 45, 'S'],
  [192, 5, 'S'],
  [230, 30, 'L'], [230, 115, 'M'], [230, 170, 'M'], [230, 225, 'S'],
];
// houses hang on the 192 rail (top at 199): box 39.5 x 30 with its cleat on top and the
// spacer at the base
export const HOUSE = {
  width: 39.5, height: 30, top: 199, cleat: 3.5, spacer: 3,
};
export const houses = [88, 130];
