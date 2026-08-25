import ChatPanel from "@/components/ChatPanel";
import Sidebar from "@/components/Sidebar";

export default function Home() {
  return (
    <main className="flex min-h-dvh">
      <Sidebar />
      <ChatPanel />
    </main>
  );
}
