import type { Metadata } from "next";

export const metadata: Metadata = { title: "لوحة مسؤول الجهة" };

export default function AdminLayout({ children }: LayoutProps<"/admin">) {
  return children;
}
