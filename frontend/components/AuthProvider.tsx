"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { ApiError } from "@/lib/api";
import {
  clearStoredToken,
  fetchCurrentUser,
  login as loginRequest,
  logout as logoutRequest,
  readStoredToken,
  storeToken,
  type AuthUser,
} from "@/lib/auth";

/**
 * `checking` هي الحالة الابتدائية دائمًا: الرمز في `localStorage` لا يُقرأ إلا
 * في المتصفح، والصفحة تُصيَّر على السيرفر أولًا. لولا هذه الحالة لومض المستخدم
 * المسجَّل على صفحة الدخول عند كل تحديث.
 *
 * `offline` حالة قائمة بذاتها لا نوع من `unauthenticated`: رمز محفوظ تعذّر
 * التحقق منه لأن السيرفر لم يردّ. طرد الموظف إلى صفحة الدخول حينها خطأ صامت
 * — الجلسة قد تكون سليمة تمامًا، والمشكلة في الرابط أو في السيرفر.
 */
type AuthStatus = "checking" | "authenticated" | "unauthenticated" | "offline";

type AuthContextValue = {
  status: AuthStatus;
  user: AuthUser | null;
  token: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  /** يعيد محاولة التحقق من الرمز المحفوظ — بعد إصلاح الرابط أو تشغيل السيرفر. */
  retrySession: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth يجب أن يُستدعى داخل <AuthProvider>.");
  }
  return context;
}

export default function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("checking");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  /** زيادته تعيد تشغيل أثر التحقق. */
  const [attempt, setAttempt] = useState(0);

  // عند فتح التطبيق: رمز محفوظ لا يكفي — قد يكون منتهيًا أو لحساب عُطّل.
  // نتحقق منه بـ/api/auth/me قبل اعتبار الجلسة قائمة.
  useEffect(() => {
    const stored = readStoredToken();
    if (!stored) {
      // القاعدة تمنع setState متزامنًا داخل الأثر تفاديًا للتصيير المتتالي.
      // هنا مقصود ولا تتالي فيه: `localStorage` غير متاح أثناء التصيير على
      // السيرفر، فحالة «لا جلسة» لا تُعرف إلا بعد أول تركيب في المتصفح.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setStatus("unauthenticated");
      return;
    }

    const controller = new AbortController();

    fetchCurrentUser(stored, controller.signal)
      .then((currentUser) => {
        setToken(stored);
        setUser(currentUser);
        setStatus("authenticated");
      })
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === "AbortError") return;

        // 401 أو 403 يعني رمزًا لم يعد صالحًا، فيُحذف ويعود المستخدم للدخول.
        if (caught instanceof ApiError) {
          clearStoredToken();
          setToken(null);
          setUser(null);
          setStatus("unauthenticated");
          return;
        }

        // انقطاع الاتصال: الرمز يبقى محفوظًا والحالة `offline`. حذفه هنا
        // يجبر الموظف على دخول جديد لن ينجح أصلًا ما دام السيرفر بعيدًا،
        // والطرد الصامت إلى صفحة الدخول يخفي السبب الحقيقي.
        setToken(null);
        setUser(null);
        setStatus("offline");
      });

    return () => controller.abort();
  }, [attempt]);

  const retrySession = useCallback(() => {
    setStatus("checking");
    setAttempt((current) => current + 1);
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const session = await loginRequest(email, password);
    storeToken(session.access_token);
    setToken(session.access_token);
    setUser(session.user);
    setStatus("authenticated");
  }, []);

  const signOut = useCallback(async () => {
    const current = token;

    // الحالة المحلية تُمسح أولًا: الرمز موقّع وبلا حالة على السيرفر
    // (انظر شرح logout في backend/app/api/auth.py)، فنداء الخروج إشعار لا
    // إبطال. فشله لا يجوز أن يُبقي المستخدم داخل التطبيق.
    clearStoredToken();
    setToken(null);
    setUser(null);
    setStatus("unauthenticated");

    if (!current) return;
    try {
      await logoutRequest(current);
    } catch {
      /* تجاهل: الخروج المحلي تمّ بالفعل. */
    }
  }, [token]);

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, token, signIn, signOut, retrySession }),
    [status, user, token, signIn, signOut, retrySession],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
