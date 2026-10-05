export default function NoAccess() {
  return (
    <main className="mx-auto max-w-xl px-4 py-20">
      <h1 className="text-xl font-semibold">You don&apos;t have dashboard access yet</h1>
      <p className="mt-2 text-sm text-muted">Access follows your MKA role: Mohtamim (own department), Regional Qaid (own region), Majlis Qaid (own Majlis), Sadr and Motamid (everything). If your role should have access, ask the Motamid office to add you.</p>
    </main>
  );
}
