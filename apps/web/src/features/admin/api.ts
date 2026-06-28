import { apiJson } from "@/lib/api";

export type Plan = {
  id: number;
  name: string;
  price_toman: number;
  duration_days: number;
};

export type AdminUser = {
  id: number;
  phone: string;
  is_admin: boolean;
  created_at?: string | null;
  has_subscription: boolean;
  subscription_expires_at?: string | null;
};

export type AdminSubscription = {
  id: number;
  phone: string;
  plan_name: string;
  starts_at?: string | null;
  expires_at?: string | null;
  status: string;
};

export type AdminPayment = {
  id: number;
  phone: string;
  plan_name: string;
  amount_toman: number;
  status: string;
  created_at?: string | null;
};

export async function getAdminStats() {
  return apiJson<{ total_users: number; active_subscriptions: number }>("/api/admin/stats");
}

export async function getAdminUsers() {
  return apiJson<{ users: AdminUser[] }>("/api/admin/users");
}

export async function getAdminSubscriptions() {
  return apiJson<{ subscriptions: AdminSubscription[] }>("/api/admin/subscriptions");
}

export async function getAdminPayments() {
  return apiJson<{ payments: AdminPayment[] }>("/api/admin/payments");
}

export async function getPlans() {
  return apiJson<{ plans: Plan[] }>("/api/plans");
}

export async function grantSubscription(phone: string, planId: number | string) {
  return apiJson<{ status: string }>("/api/admin/grant", {
    method: "POST",
    body: JSON.stringify({ phone, plan_id: planId }),
  });
}

export async function revokeSubscription(subscriptionId: number) {
  return apiJson<{ status: string }>("/api/admin/revoke", {
    method: "POST",
    body: JSON.stringify({ subscription_id: subscriptionId }),
  });
}
