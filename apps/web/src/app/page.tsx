import { AuthGate } from "@/components/AuthGate";
import { ChatApp } from "@/features/chat/components/ChatApp";
import { getServerAuth } from "@/lib/server-auth";

export default async function Home() {
  const auth = await getServerAuth();

  if (auth.state === "guest") {
    return <AuthGate auth={{ state: "guest" }} />;
  }

  if (auth.state === "unsubscribed") {
    return <AuthGate auth={{ state: "unsubscribed", userLabel: auth.userLabel }} />;
  }

  return <ChatApp user={{ label: auth.userLabel, isAdmin: auth.isAdmin }} />;
}
