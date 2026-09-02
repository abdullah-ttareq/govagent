import RequireAuth from "@/components/RequireAuth";
import Workspace from "@/components/Workspace";

export default function Home() {
  return (
    <RequireAuth>
      <Workspace />
    </RequireAuth>
  );
}
