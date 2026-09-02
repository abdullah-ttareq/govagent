import RequireAdmin from "@/components/RequireAdmin";
import RequireAuth from "@/components/RequireAuth";
import AdminDashboard from "@/components/admin/AdminDashboard";

export default function AdminPage() {
  return (
    <RequireAuth>
      <RequireAdmin>
        <AdminDashboard />
      </RequireAdmin>
    </RequireAuth>
  );
}
