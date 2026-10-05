/**
 * Canonical surah data. Verse counts use standard (Hafs) numbering, where the
 * Bismillah is NOT counted as verse 1 of chapters 2-8 and 10-114. This is the
 * numbering people use when citing ("2:255"). Al Islam's own numbering differs;
 * see fetch.ts for the mapping.
 */

export interface Surah {
  number: number;
  name: string; // primary transliteration
  verses: number; // standard verse count
  aliases: string[]; // other common transliterations
}

const S = (number: number, name: string, verses: number, ...aliases: string[]): Surah => ({ number, name, verses, aliases });

export const SURAHS: Surah[] = [
  S(1, 'Al-Fatiha', 7, 'Fatihah', 'Al-Fatihah', 'Al-Fatiha', 'Opening'),
  S(2, 'Al-Baqarah', 286, 'Baqara', 'Al-Baqara', 'The Cow'),
  S(3, "Ali 'Imran", 200, 'Al-Imran', 'Aal-e-Imran', 'Ali Imran', 'Al Imran', 'Aal Imran'),
  S(4, 'An-Nisa', 176, 'Nisa', "An-Nisa'", 'Al-Nisa'),
  S(5, "Al-Ma'idah", 120, 'Maidah', 'Al-Maida', 'Al-Maidah', 'Maida'),
  S(6, "Al-An'am", 165, 'Anam', 'Al-Anam', "Al-An'aam"),
  S(7, "Al-A'raf", 206, 'Araf', 'Al-Araf', "Al-A'raaf"),
  S(8, 'Al-Anfal', 75, 'Anfal'),
  S(9, 'At-Tawbah', 129, 'Tawbah', 'At-Tauba', 'Tauba', 'Al-Bara\'ah', 'Bara\'ah', 'Barah'),
  S(10, 'Yunus', 109, 'Yoonus'),
  S(11, 'Hud', 123, 'Hood'),
  S(12, 'Yusuf', 111, 'Yousuf', 'Yousef'),
  S(13, "Ar-Ra'd", 43, 'Rad', 'Ar-Rad'),
  S(14, 'Ibrahim', 52, 'Ibraheem'),
  S(15, 'Al-Hijr', 99, 'Hijr'),
  S(16, 'An-Nahl', 128, 'Nahl'),
  S(17, "Al-Isra'", 111, 'Isra', 'Al-Isra', 'Bani Isra\'il', 'Bani Israil'),
  S(18, 'Al-Kahf', 110, 'Kahf'),
  S(19, 'Maryam', 98, 'Mariam'),
  S(20, 'Ta-Ha', 135, 'Taha', 'Ta Ha'),
  S(21, "Al-Anbiya'", 112, 'Anbiya', 'Al-Anbiya'),
  S(22, 'Al-Hajj', 78, 'Hajj'),
  S(23, "Al-Mu'minun", 118, 'Muminun', 'Al-Muminun', 'Al-Mominoon', 'Al-Mu\'minoon'),
  S(24, 'An-Nur', 64, 'Nur', 'An-Noor', 'Noor'),
  S(25, 'Al-Furqan', 77, 'Furqan'),
  S(26, "Ash-Shu'ara'", 227, 'Shuara', 'Ash-Shuara', 'Al-Shuara'),
  S(27, 'An-Naml', 93, 'Naml'),
  S(28, 'Al-Qasas', 88, 'Qasas'),
  S(29, "Al-'Ankabut", 69, 'Ankabut', 'Al-Ankabut'),
  S(30, 'Ar-Rum', 60, 'Rum', 'Ar-Room', 'Room'),
  S(31, 'Luqman', 34, 'Luqmaan'),
  S(32, 'As-Sajdah', 30, 'Sajdah', 'As-Sajda', 'Sajda'),
  S(33, 'Al-Ahzab', 73, 'Ahzab'),
  S(34, "Saba'", 54, 'Saba', 'Sabaa'),
  S(35, 'Fatir', 45, 'Al-Fatir', 'Malaika', 'Al-Mala\'ikah'),
  S(36, 'Ya-Sin', 83, 'Yasin', 'Ya Sin', 'Yaseen', 'Ya-Seen'),
  S(37, 'As-Saffat', 182, 'Saffat', 'As-Saaffat'),
  S(38, 'Sad', 88, 'Saad'),
  S(39, 'Az-Zumar', 75, 'Zumar'),
  S(40, 'Ghafir', 85, 'Al-Mu\'min', 'Al-Mumin', 'Mumin', 'Al-Ghafir'),
  S(41, 'Fussilat', 54, 'Ha-Mim Sajdah', 'Ha Mim Sajdah', 'Fusilat'),
  S(42, 'Ash-Shura', 53, 'Shura', 'Ash-Shuraa'),
  S(43, 'Az-Zukhruf', 89, 'Zukhruf'),
  S(44, 'Ad-Dukhan', 59, 'Dukhan', 'Ad-Dukhaan'),
  S(45, 'Al-Jathiyah', 37, 'Jathiyah', 'Al-Jathiya', 'Jathiya'),
  S(46, 'Al-Ahqaf', 35, 'Ahqaf'),
  S(47, 'Muhammad', 38),
  S(48, 'Al-Fath', 29, 'Fath'),
  S(49, 'Al-Hujurat', 18, 'Hujurat'),
  S(50, 'Qaf', 45),
  S(51, 'Adh-Dhariyat', 60, 'Dhariyat', 'Az-Zariyat', 'Zariyat'),
  S(52, 'At-Tur', 49, 'Tur'),
  S(53, 'An-Najm', 62, 'Najm'),
  S(54, 'Al-Qamar', 55, 'Qamar'),
  S(55, 'Ar-Rahman', 78, 'Rahman', 'Ar-Rehman', 'Rehman'),
  S(56, "Al-Waqi'ah", 96, 'Waqiah', 'Al-Waqiah', 'Al-Waqia', 'Waqia'),
  S(57, 'Al-Hadid', 29, 'Hadid'),
  S(58, 'Al-Mujadilah', 22, 'Mujadilah', 'Al-Mujadila', 'Mujadila'),
  S(59, 'Al-Hashr', 24, 'Hashr'),
  S(60, 'Al-Mumtahanah', 13, 'Mumtahanah', 'Al-Mumtahina', 'Mumtahina'),
  S(61, 'As-Saff', 14, 'Saff'),
  S(62, "Al-Jumu'ah", 11, 'Jumuah', 'Al-Jumuah', 'Al-Jumua', 'Jumua'),
  S(63, 'Al-Munafiqun', 11, 'Munafiqun', 'Al-Munafiqoon'),
  S(64, 'At-Taghabun', 18, 'Taghabun'),
  S(65, 'At-Talaq', 12, 'Talaq'),
  S(66, 'At-Tahrim', 12, 'Tahrim'),
  S(67, 'Al-Mulk', 30, 'Mulk'),
  S(68, 'Al-Qalam', 52, 'Qalam'),
  S(69, 'Al-Haqqah', 52, 'Haqqah', 'Al-Haaqqah'),
  S(70, "Al-Ma'arij", 44, 'Maarij', 'Al-Maarij'),
  S(71, 'Nuh', 28, 'Noah'),
  S(72, 'Al-Jinn', 28, 'Jinn'),
  S(73, 'Al-Muzzammil', 20, 'Muzzammil'),
  S(74, 'Al-Muddaththir', 56, 'Muddaththir', 'Al-Muddathir', 'Muddathir'),
  S(75, 'Al-Qiyamah', 40, 'Qiyamah', 'Al-Qiyama', 'Qiyama'),
  S(76, 'Al-Insan', 31, 'Insan', 'Ad-Dahr', 'Dahr'),
  S(77, 'Al-Mursalat', 50, 'Mursalat'),
  S(78, "An-Naba'", 40, 'Naba', 'An-Naba'),
  S(79, "An-Nazi'at", 46, 'Naziat', 'An-Naziat'),
  S(80, "'Abasa", 42, 'Abasa'),
  S(81, 'At-Takwir', 29, 'Takwir'),
  S(82, 'Al-Infitar', 19, 'Infitar'),
  S(83, 'Al-Mutaffifin', 36, 'Mutaffifin'),
  S(84, 'Al-Inshiqaq', 25, 'Inshiqaq'),
  S(85, 'Al-Buruj', 22, 'Buruj'),
  S(86, 'At-Tariq', 17, 'Tariq'),
  S(87, "Al-A'la", 19, 'Ala', 'Al-Ala'),
  S(88, 'Al-Ghashiyah', 26, 'Ghashiyah', 'Al-Ghashiya', 'Ghashiya'),
  S(89, 'Al-Fajr', 30, 'Fajr'),
  S(90, 'Al-Balad', 20, 'Balad'),
  S(91, 'Ash-Shams', 15, 'Shams'),
  S(92, 'Al-Layl', 21, 'Layl', 'Al-Lail', 'Lail'),
  S(93, 'Ad-Duha', 11, 'Duha', 'Ad-Dhuha', 'Dhuha'),
  S(94, 'Ash-Sharh', 8, 'Sharh', 'Al-Inshirah', 'Inshirah', 'Alam Nashrah'),
  S(95, 'At-Tin', 8, 'Tin'),
  S(96, "Al-'Alaq", 19, 'Alaq', 'Al-Alaq', 'Iqra'),
  S(97, 'Al-Qadr', 5, 'Qadr'),
  S(98, 'Al-Bayyinah', 8, 'Bayyinah', 'Al-Bayyina', 'Bayyina'),
  S(99, 'Az-Zalzalah', 8, 'Zalzalah', 'Az-Zilzal', 'Zilzal', 'Al-Zalzalah'),
  S(100, "Al-'Adiyat", 11, 'Adiyat', 'Al-Adiyat'),
  S(101, "Al-Qari'ah", 11, 'Qariah', 'Al-Qariah', 'Al-Qaria', 'Qaria'),
  S(102, 'At-Takathur', 8, 'Takathur'),
  S(103, "Al-'Asr", 3, 'Asr', 'Al-Asr'),
  S(104, 'Al-Humazah', 9, 'Humazah', 'Al-Humaza', 'Humaza'),
  S(105, 'Al-Fil', 5, 'Fil'),
  S(106, 'Quraysh', 4, 'Quraish'),
  S(107, "Al-Ma'un", 7, 'Maun', 'Al-Maun'),
  S(108, 'Al-Kawthar', 3, 'Kawthar', 'Al-Kauthar', 'Kauthar'),
  S(109, 'Al-Kafirun', 6, 'Kafirun', 'Al-Kafiroon', 'Kafiroon'),
  S(110, 'An-Nasr', 3, 'Nasr'),
  S(111, 'Al-Masad', 5, 'Masad', 'Al-Lahab', 'Lahab', 'Tabbat'),
  S(112, 'Al-Ikhlas', 4, 'Ikhlas', 'Al-Ikhlaas'),
  S(113, 'Al-Falaq', 5, 'Falaq'),
  S(114, 'An-Nas', 6, 'Nas', 'An-Naas', 'Naas'),
];

export const TOTAL_VERSES = SURAHS.reduce((n, s) => n + s.verses, 0); // 6236

/** Lowercase, strip diacritics/apostrophes/hyphens/spaces. */
export function normalizeName(raw: string): string {
  return raw
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z]/g, '');
}

const ARTICLE = /^(?:al|an|ar|as|ash|at|ad|adh|az|ath|aal)(?=[a-z]{3,})/;

/** Normalized keys for a name: full form and form without a leading Arabic article. */
function keysFor(raw: string): string[] {
  const full = normalizeName(raw);
  const bare = full.replace(ARTICLE, '');
  return bare === full ? [full] : [full, bare];
}

const LOOKUP = new Map<string, number>();
for (const s of SURAHS) {
  for (const n of [s.name, ...s.aliases]) {
    for (const k of keysFor(n)) if (!LOOKUP.has(k)) LOOKUP.set(k, s.number);
  }
}

/** Resolve a surah name (any common transliteration) to its number, or null. */
export function surahNumberFromName(raw: string): number | null {
  for (const k of keysFor(raw)) {
    const n = LOOKUP.get(k);
    if (n) return n;
  }
  return null;
}

export function surahByNumber(n: number): Surah | undefined {
  return SURAHS[n - 1];
}

/** Validate a standard-numbering reference. Returns an error string, or null if valid. */
export function validateReference(chapter: number, start: number, end: number): string | null {
  const s = surahByNumber(chapter);
  if (!Number.isInteger(chapter) || !s) return `chapter ${chapter} is not in 1..114`;
  if (!Number.isInteger(start) || start < 1) return `verse ${start} must be >= 1`;
  if (!Number.isInteger(end) || end < start) return `range end ${end} is before start ${start}`;
  if (end > s.verses) return `chapter ${chapter} (${s.name}) has ${s.verses} verses; ${end} is out of range`;
  return null;
}
