export interface DepartmentSeed {
  slug: string; name: string; translation: string; mailboxPrefix: string;
}

const d = (name: string, translation: string, mailboxPrefix?: string): DepartmentSeed => {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return { slug, name, translation, mailboxPrefix: mailboxPrefix ?? slug.replace(/-/g, "") };
};

/**
 * Canonical 21 departments. mailboxPrefix is PROVISIONAL except Aitmad (motamid)
 * and Nau Mubaeen (rishtanata reuse, per umbrella spec section 4); the fork's
 * identity_rules file is the source of truth and must be reconciled.
 */
export const DEPARTMENTS: DepartmentSeed[] = [
  d("Aitmad", "General Secretary", "motamid"),
  d("Amoomi", "Amoomi"),
  d("Amoor-e-Tuluba", "Student Affairs"),
  d("Atfal", "Boys 7-15"),
  d("Ishaat", "Publications"),
  d("Khidmat-e-Khalq", "Service to Humanity"),
  d("Maal", "Finance"),
  d("Mohasib", "Audit"),
  d("Nau Mubaeen", "New Converts", "rishtanata"),
  d("Rishta Nata", "Marital Affairs"),
  d("Sanat-o-Tijarat", "Industry and Trade"),
  d("Sehat-e-Jismani", "Physical Health"),
  d("Tabligh", "Preaching"),
  d("Tahrik-e-Jadid", "Tahrik-e-Jadid"),
  d("Tajneed", "Census"),
  d("Taleem", "Education"),
  d("Tarbiyyat", "Moral Training"),
  d("Waqar-e-Amal", "Dignity of Labor"),
  d("Waqf-e-Nau", "Waqf-e-Nau"),
  d("Wasiyyat", "Wasiyyat"),
  d("New Immigrants", "New Immigrants"),
];
