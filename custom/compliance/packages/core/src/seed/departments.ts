export interface DepartmentSeed {
  slug: string; name: string; translation: string; mailboxPrefix: string;
}

const d = (name: string, translation: string, mailboxPrefix?: string): DepartmentSeed => {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return { slug, name, translation, mailboxPrefix: mailboxPrefix ?? slug };
};

/** Canonical 21 departments with the REAL mailbox prefixes (coordinator order 2). Local Atfal roles live on @atfalusa.org as nazim.{majlis}/murabbi.{majlis}. */
export const DEPARTMENTS: DepartmentSeed[] = [
  d("Aitmad", "General Secretary", "motamid"),
  d("Amoomi", "Amoomi", "amoomi"),
  d("Amoor-e-Tuluba", "Student Affairs", "amoor-e-tuluba"),
  d("Atfal", "Boys 7-15", "atfal"),
  d("Ishaat", "Publications", "ishaat"),
  d("Khidmat-e-Khalq", "Service to Humanity", "khidmat-e-khalq"),
  d("Maal", "Finance", "maal"),
  d("Mohasib", "Audit", "mohasib"),
  d("Nau Mubaeen", "New Converts", "nau-mubaeen"),
  d("Rishta Nata", "Marital Affairs", "rishtanata"),
  d("Sanat-o-Tijarat", "Industry and Trade", "sanat-o-tijarat"),
  d("Sehat-e-Jismani", "Physical Health", "sehat-e-jismani"),
  d("Tabligh", "Preaching", "tabligh"),
  d("Tahrik-e-Jadid", "Tahrik-e-Jadid", "tahrik-e-jadid"),
  d("Tajneed", "Census", "tajneed"),
  d("Taleem", "Education", "taleem"),
  d("Tarbiyyat", "Moral Training", "tarbiyyat"),
  d("Waqar-e-Amal", "Dignity of Labor", "waqar-e-amal"),
  d("Waqf-e-Nau", "Waqf-e-Nau", "waqf-e-nau"),
  d("Wasiyyat", "Wasiyyat", "wasiyyat"),
  d("New Immigrants", "New Immigrants", "immigrants"),
];
