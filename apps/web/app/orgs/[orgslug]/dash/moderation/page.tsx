import ModerationQueue from '@components/Dashboard/Moderation/ModerationQueue'

export const metadata = {
  title: 'Moderation',
  robots: { index: false, follow: false },
}

export default function ModerationPage() {
  return <ModerationQueue />
}
