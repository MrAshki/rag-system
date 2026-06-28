import { AuthGate } from "@/components/AuthGate";
import { GalleryClient } from "@/features/library/components/GalleryClient";
import { getServerAuth } from "@/lib/server-auth";

export default async function GalleryPage() {
  const auth = await getServerAuth();

  if (auth.state === "guest") {
    return <AuthGate auth={{ state: "guest" }} />;
  }

  if (auth.state === "unsubscribed") {
    return <AuthGate auth={{ state: "unsubscribed", userLabel: auth.userLabel }} />;
  }

  return <GalleryClient />;
}
