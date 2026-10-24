import { auth } from "@/auth";
import NavBar from "@/components/NavBar";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await auth();
  return (
    <div className="flex flex-1 flex-col">
      <NavBar username={session?.username} />
      <main className="flex-1 px-4 py-6">{children}</main>
    </div>
  );
}
