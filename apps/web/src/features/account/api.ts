import { apiJson } from "@/lib/api";

export type Profile = {
  first_name?: string | null;
  last_name?: string | null;
  email?: string | null;
  phone?: string | null;
  birth_date?: string | null;
  created_at?: string | null;
  has_password?: boolean;
};

export type Payment = {
  id: number;
  plan_name?: string | null;
  amount_toman?: number | string | null;
  status: string;
  created_at?: string | null;
};

export async function getProfile() {
  return apiJson<Profile>("/api/profile");
}

export async function updateProfile(payload: {
  first_name: string;
  last_name: string;
  email: string;
  birth_date?: string | null;
  password?: string;
}) {
  return apiJson<{ status: string }>("/api/profile", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getProfilePayments() {
  return apiJson<{ payments: Payment[] }>("/api/profile/payments");
}
