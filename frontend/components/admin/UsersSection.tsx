"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import Alert from "@/components/ui/Alert";
import Button from "@/components/ui/Button";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import EmptyState from "@/components/ui/EmptyState";
import ErrorNotice from "@/components/ui/ErrorNotice";
import Input from "@/components/ui/Input";
import Modal from "@/components/ui/Modal";
import {
  ROLE_LABELS,
  createUser,
  disableUser,
  listUsers,
  updateUser,
  validateFullName,
  validateNewPassword,
  type DirectoryUser,
} from "@/lib/admin";
import { ApiError } from "@/lib/api";
import { validateEmail, type UserRole } from "@/lib/auth";
import { describeFailure, describeFailureDetail, type Failure } from "@/lib/errors";

type AddForm = {
  email: string;
  full_name: string;
  role: UserRole;
  password: string;
};

const EMPTY_FORM: AddForm = {
  email: "",
  full_name: "",
  role: "employee",
  password: "",
};

export default function UsersSection({
  onDirectoryChanged,
}: {
  /** يُستدعى بعد كل تغيّر يمسّ المقاعد، لتحديث بطاقة الاشتراك. */
  onDirectoryChanged: () => void;
}) {
  const { token, user: currentUser, endExpiredSession } = useAuth();

  const [users, setUsers] = useState<DirectoryUser[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [failure, setFailure] = useState<Failure | null>(null);
  /** خطأ إجراء على صفّ بعينه — يظهر أعلى الجدول لا يستبدله. */
  const [actionError, setActionError] = useState<string | null>(null);
  /** معرّف الموظف الذي يجري عليه إجراء الآن، لتعطيل أزراره وحدها. */
  const [busyId, setBusyId] = useState<number | null>(null);

  const [isAddOpen, setIsAddOpen] = useState(false);
  const [form, setForm] = useState<AddForm>(EMPTY_FORM);
  const [formErrors, setFormErrors] = useState<Partial<Record<keyof AddForm, string>>>({});
  const [addError, setAddError] = useState<string | null>(null);
  const [isAdding, setIsAdding] = useState(false);

  const [disableTarget, setDisableTarget] = useState<DirectoryUser | null>(null);
  const [disableError, setDisableError] = useState<string | null>(null);
  const [isDisabling, setIsDisabling] = useState(false);

  /** رمز لم يعد صالحًا: تُنهى الجلسة فيحوّل `RequireAuth` إلى `/login`. */
  const expireIfUnauthorized = useCallback(
    (caught: unknown) => {
      if (caught instanceof ApiError && caught.status === 401) endExpiredSession();
    },
    [endExpiredSession],
  );

  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      if (!token) return;
      try {
        const result = await listUsers(token, signal);
        setUsers(result.users);
        setFailure(null);
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setFailure(describeFailureDetail(caught, "تعذّر تحميل قائمة الموظفين."));
        expireIfUnauthorized(caught);
      } finally {
        setIsLoading(false);
      }
    },
    [token, expireIfUnauthorized],
  );

  useEffect(() => {
    const controller = new AbortController();
    // جلب أولي من السيرفر — النمط الذي تستثنيه القاعدة نفسها: مزامنة مع
    // نظام خارجي، والكتابة تحدث بعد انتهاء الطلب لا داخل التصيير.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  function replaceUser(updated: DirectoryUser) {
    setUsers((current) =>
      current.map((item) => (item.id === updated.id ? updated : item)),
    );
  }

  async function submitAdd(event: React.FormEvent) {
    event.preventDefault();
    if (!token || isAdding) return;

    const errors: Partial<Record<keyof AddForm, string>> = {};
    const emailError = validateEmail(form.email);
    const nameError = validateFullName(form.full_name);
    const passwordError = validateNewPassword(form.password);
    if (emailError) errors.email = emailError;
    if (nameError) errors.full_name = nameError;
    if (passwordError) errors.password = passwordError;

    setFormErrors(errors);
    setAddError(null);
    if (Object.keys(errors).length > 0) return;

    setIsAdding(true);
    try {
      const created = await createUser(token, {
        email: form.email.trim(),
        full_name: form.full_name.trim(),
        role: form.role,
        password: form.password,
      });
      setUsers((current) => [...current, created]);
      setForm(EMPTY_FORM);
      setIsAddOpen(false);
      onDirectoryChanged();
    } catch (caught) {
      // 409 هنا حالتان: بريد مكرر، أو مقاعد مستنفدة. رسالة الـBackend
      // تفرّق بينهما بنصّها، فتُعرض كما وردت.
      setAddError(describeFailure(caught, "تعذّرت إضافة الموظف."));
      expireIfUnauthorized(caught);
    } finally {
      setIsAdding(false);
    }
  }

  async function changeRole(target: DirectoryUser, role: UserRole) {
    if (!token) return;
    setBusyId(target.id);
    setActionError(null);
    try {
      replaceUser(await updateUser(token, target.id, { role }));
    } catch (caught) {
      setActionError(describeFailure(caught, "تعذّر تغيير دور الموظف."));
      expireIfUnauthorized(caught);
    } finally {
      setBusyId(null);
    }
  }

  async function setActive(target: DirectoryUser, isActive: boolean) {
    if (!token) return;
    setBusyId(target.id);
    setActionError(null);
    try {
      // التعطيل عبر DELETE والتفعيل عبر PATCH — كما يعرّفهما الـBackend.
      const updated = isActive
        ? await updateUser(token, target.id, { is_active: true })
        : await disableUser(token, target.id);
      replaceUser(updated);
      onDirectoryChanged();
    } catch (caught) {
      // إعادة التفعيل قد تُرفض بـ409 إن اكتملت المقاعد.
      setActionError(
        describeFailure(
          caught,
          isActive ? "تعذّر إعادة تفعيل الحساب." : "تعذّر تعطيل الحساب.",
        ),
      );
      expireIfUnauthorized(caught);
    } finally {
      setBusyId(null);
    }
  }

  async function confirmDisable() {
    if (!disableTarget || isDisabling) return;
    setIsDisabling(true);
    setDisableError(null);
    try {
      replaceUser(await disableUser(token!, disableTarget.id));
      setDisableTarget(null);
      onDirectoryChanged();
    } catch (caught) {
      setDisableError(describeFailure(caught, "تعذّر تعطيل الحساب."));
      expireIfUnauthorized(caught);
    } finally {
      setIsDisabling(false);
    }
  }

  if (isLoading) {
    return (
      <ul className="space-y-2" aria-label="جارٍ تحميل الموظفين">
        {[0, 1, 2, 3].map((index) => (
          <li key={index} className="gv-skeleton h-14" />
        ))}
      </ul>
    );
  }

  if (failure) {
    return (
      <ErrorNotice
        failure={failure}
        onRetry={() => {
          setIsLoading(true);
          void refresh();
        }}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted">
          {users.length.toLocaleString("ar")} موظف في جهتك
        </p>
        <Button onClick={() => setIsAddOpen(true)}>+ إضافة موظف</Button>
      </div>

      {actionError && <Alert tone="error">{actionError}</Alert>}

      {users.length === 0 ? (
        <EmptyState
          title="لا يوجد موظفون بعد."
          hint="أضف أول موظف ليتمكن من تسجيل الدخول واستخدام المساعد."
        />
      ) : (
        <div className="gv-table-wrap">
          <table className="gv-table">
            <thead>
              <tr>
                <th scope="col">الموظف</th>
                <th scope="col">الدور</th>
                <th scope="col">الحالة</th>
                <th scope="col">
                  <span className="sr-only">إجراءات</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {users.map((item) => {
                // المسؤول لا يغيّر دوره ولا يعطّل نفسه — يفرضه الـBackend،
                // وإخفاء الأزرار يمنع محاولة محكومة بالفشل.
                const isSelf = item.id === currentUser?.id;
                const isBusy = busyId === item.id;

                return (
                  <tr key={item.id}>
                    <td>
                      <span className="block font-semibold">{item.full_name}</span>
                      <span className="block text-xs text-muted" dir="ltr">
                        {item.email}
                      </span>
                    </td>

                    <td>
                      {isSelf ? (
                        <span className="text-sm">{ROLE_LABELS[item.role]}</span>
                      ) : (
                        <select
                          className="gv-input !min-h-0 !py-2 text-sm"
                          value={item.role}
                          disabled={isBusy}
                          aria-label={`دور ${item.full_name}`}
                          onChange={(event) =>
                            void changeRole(item, event.target.value as UserRole)
                          }
                        >
                          <option value="employee">موظف</option>
                          <option value="admin">مسؤول الجهة</option>
                        </select>
                      )}
                    </td>

                    <td>
                      <span
                        className={`gv-badge ${item.is_active ? "gv-badge--ok" : "gv-badge--off"}`}
                      >
                        {item.is_active ? "نشط" : "معطّل"}
                      </span>
                    </td>

                    <td className="text-end">
                      {isSelf ? (
                        <span className="text-xs text-muted">حسابك</span>
                      ) : item.is_active ? (
                        <Button
                          variant="ghost"
                          disabled={isBusy}
                          onClick={() => {
                            setDisableTarget(item);
                            setDisableError(null);
                          }}
                        >
                          تعطيل
                        </Button>
                      ) : (
                        <Button
                          variant="ghost"
                          isLoading={isBusy}
                          loadingLabel="جارٍ التفعيل…"
                          onClick={() => void setActive(item, true)}
                        >
                          إعادة تفعيل
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="gv-hint">
        الحساب يُعطَّل ولا يُحذف: الموظف مرتبط بمحادثاته وملفاته وسجل تدقيقه،
        وحذفه يترك تاريخًا بلا صاحب. الحساب المعطّل لا يشغل مقعدًا.
      </p>

      <Modal
        isOpen={isAddOpen}
        onClose={() => !isAdding && setIsAddOpen(false)}
        title="إضافة موظف"
      >
        <form onSubmit={submitAdd} noValidate className="mt-4 space-y-4">
          <Input
            label="البريد الإلكتروني"
            dir="ltr"
            autoCapitalize="none"
            spellCheck={false}
            placeholder="name@entity.gov.sa"
            hint="البريد هوية الدخول، وغير قابل للتعديل بعد الإنشاء."
            value={form.email}
            disabled={isAdding}
            error={formErrors.email}
            onChange={(event) =>
              setForm((current) => ({ ...current, email: event.target.value }))
            }
          />

          <Input
            label="الاسم الكامل"
            value={form.full_name}
            disabled={isAdding}
            error={formErrors.full_name}
            onChange={(event) =>
              setForm((current) => ({ ...current, full_name: event.target.value }))
            }
          />

          <div className="gv-field">
            <label className="gv-label" htmlFor="new-user-role">
              الدور
            </label>
            <select
              id="new-user-role"
              className="gv-input"
              value={form.role}
              disabled={isAdding}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  role: event.target.value as UserRole,
                }))
              }
            >
              <option value="employee">موظف</option>
              <option value="admin">مسؤول الجهة</option>
            </select>
          </div>

          <Input
            label="كلمة المرور الأولى"
            type="password"
            dir="ltr"
            autoComplete="new-password"
            hint="سلّمها للموظف ليغيّرها بعد أول دخول. ٨ أحرف فأكثر."
            value={form.password}
            disabled={isAdding}
            error={formErrors.password}
            onChange={(event) =>
              setForm((current) => ({ ...current, password: event.target.value }))
            }
          />

          {addError && <Alert tone="error">{addError}</Alert>}

          <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-start">
            <Button
              type="button"
              variant="secondary"
              disabled={isAdding}
              onClick={() => setIsAddOpen(false)}
            >
              إلغاء
            </Button>
            <Button type="submit" isLoading={isAdding} loadingLabel="جارٍ الإضافة…">
              إضافة
            </Button>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        isOpen={disableTarget !== null}
        title="تعطيل حساب موظف"
        message={`سيُمنع «${disableTarget?.full_name ?? ""}» من تسجيل الدخول ومن كل مسار محمي. محادثاته وملفاته وسجله تبقى كما هي، ويمكنك إعادة تفعيله لاحقًا.`}
        confirmLabel="تعطيل الحساب"
        isBusy={isDisabling}
        error={disableError}
        onConfirm={confirmDisable}
        onCancel={() => setDisableTarget(null)}
      />
    </div>
  );
}
