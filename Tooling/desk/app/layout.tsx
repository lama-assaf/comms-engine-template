import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { loadContext } from "@/lib/desk";
import { brandName } from "@/lib/paths";

export async function generateMetadata(): Promise<Metadata> {
  return {
    title: `${brandName()} desk`,
    description: "The social engine's calendar, quick actions and reviews.",
  };
}

// Every page reads the database on each request. The engine writes it from
// outside the process, so a cached render would show a cycle that has already
// moved on.
export const dynamic = "force-dynamic";

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const { meta } = await loadContext();
  const push = meta.get("last_push");
  const priv = meta.get("private_handles_present") === "1";
  return (
    <html lang="en">
      <body>
        <header className="top">
          <div className="inner">
            <h1>
              {brandName()} desk <span>· social engine</span>
            </h1>
            <span className="stale">
              {push ? `pushed ${push.slice(0, 16).replace("T", " ")}Z` : "never pushed — run desk_sync.py --push"}
              {priv ? "" : " · stealth list missing: the gate blocks"}
            </span>
            <nav className="tabs">
              <Link href="/">Calendar</Link>
              <Link href="/queue">Waiting on you</Link>
              <Link href="/reviews">Reviews</Link>
            </nav>
          </div>
        </header>
        <main className="wrap">{children}</main>
      </body>
    </html>
  );
}
