import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Modal } from '@/components/ui/modal/modal';
import { IModalProps } from '@/interfaces/common';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import * as z from 'zod';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { TenantRole } from '../constants';

interface EditUserModalProps extends IModalProps<{ nickname: string; role: TenantRole }> {
  userData?: {
    nickname: string;
    email: string;
    role: TenantRole;
  };
}

const EditUserModal = ({
  visible,
  hideModal,
  loading,
  onOk,
  userData,
}: EditUserModalProps) => {
  const { t } = useTranslation();

  const formSchema = z.object({
    nickname: z.string().min(1, { message: t('common.required') }),
    role: z.nativeEnum(TenantRole),
  });

  type FormData = z.infer<typeof formSchema>;

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      nickname: userData?.nickname || '',
      role: userData?.role || TenantRole.Normal,
    },
  });

  const handleOk = async (data: FormData) => {
    return onOk?.(data);
  };

  return (
    <Modal
      title={t('setting.editUser')}
      open={visible || false}
      onOpenChange={(open) => !open && hideModal?.()}
      onOk={form.handleSubmit(handleOk)}
      confirmLoading={loading}
      okText={t('common.save')}
      cancelText={t('common.cancel')}
    >
      <Form {...form}>
        <form onSubmit={form.handleSubmit(handleOk)} className="space-y-4">
          <div className="space-y-2">
            <FormLabel>{t('setting.email')}</FormLabel>
            <Input
              value={userData?.email || ''}
              disabled
              className="bg-bg-input"
            />
            <p className="text-xs text-text-secondary">
              {t('setting.emailCannotBeChanged')}
            </p>
          </div>

          <FormField
            control={form.control}
            name="nickname"
            render={({ field }) => (
              <FormItem>
                <FormLabel required>{t('common.name')}</FormLabel>
                <FormControl>
                  <Input placeholder={t('common.name')} {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="role"
            render={({ field }) => (
              <FormItem>
                <FormLabel required>{t('setting.role')}</FormLabel>
                <Select onValueChange={field.onChange} defaultValue={field.value}>
                  <FormControl>
                    <SelectTrigger>
                      <SelectValue placeholder={t('setting.selectRole')} />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectItem value={TenantRole.Normal}>
                      {t('setting.roleMember')}
                    </SelectItem>
                    <SelectItem value={TenantRole.Owner}>
                      {t('setting.roleOwner')}
                    </SelectItem>
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
        </form>
      </Form>
    </Modal>
  );
};

export default EditUserModal;
