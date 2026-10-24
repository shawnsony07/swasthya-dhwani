import { redirect } from "next/navigation";
import { auth, signIn } from "@/auth";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ callbackUrl?: string }>;
}) {
  const session = await auth();
  const { callbackUrl } = await searchParams;

  if (session) {
    redirect(callbackUrl ?? "/dashboard");
  }

  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-6 px-4 text-center">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">
          Swasthya-Dhwani Dashboard
        </h1>
        <p className="mt-2 text-slate-600">
          Sign in with your hospital account to view and approve triage alerts.
        </p>
      </div>
      <form
        action={async () => {
          "use server";
          await signIn("keycloak", { redirectTo: callbackUrl ?? "/dashboard" });
        }}
      >
        <button
          type="submit"
          className="rounded-md bg-blue-600 px-6 py-3 text-base font-semibold text-white hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-800"
        >
          Sign in with Keycloak
        </button>
      </form>
      <p className="max-w-md text-xs text-slate-400">
        Synthetic / demo data — not a real clinical tool.
      </p>
    </main>
  );
}
