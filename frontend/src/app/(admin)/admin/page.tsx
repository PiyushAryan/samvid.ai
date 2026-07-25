import { redirect } from "next/navigation";

export default function AdminIndexRoute() {
  redirect("/admin/users");
}
