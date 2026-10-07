"use client";

import { ErrorState } from "@/components/StateViews";

export default function GlobalError({ error }: { error: Error & { digest?: string } }) {
  return (
    <html>
      <body>
        <div className="mx-auto max-w-6xl px-4 py-6">
          <ErrorState title="Something went wrong" detail={process.env.NODE_ENV === "development" ? error.message : undefined} />
        </div>
      </body>
    </html>
  );
}
