import { AuthGate } from "@/components/AuthGate";
import { ProfileClient } from "@/features/account/components/ProfileClient";
import { getServerAuth } from "@/lib/server-auth";

export default async function ProfilePage() {
  const auth = await getServerAuth();

  if (auth.state === "guest") {
    return <AuthGate auth={{ state: "guest" }} />;
  }

  return <ProfileClient />;
}
