/**
 * ConditionRowActions — per-row dropdown menu (⋮ IconButton + Menu/MenuItem).
 * Actions: "Добавить выше", "Добавить ниже", "Удалить", "Переместить вверх",
 * "Переместить вниз", "Дублировать".
 * Delete opens a confirm Dialog before calling onRemove.
 */

import { memo, useRef, useState } from 'react';
import {
  Button,
  Dialog,
  IconButton,
  Menu,
  MenuItem,
  Stack,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

export interface ConditionRowActionsProps {
  rowIdx: number;
  isFirst: boolean;
  isLast: boolean;
  onAddAbove: () => void;
  onAddBelow: () => void;
  onRemove: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onDuplicate: () => void;
  disabled?: boolean;
}

function ConditionRowActionsBase({
  rowIdx,
  isFirst,
  isLast,
  onAddAbove,
  onAddBelow,
  onRemove,
  onMoveUp,
  onMoveDown,
  onDuplicate,
  disabled,
}: ConditionRowActionsProps) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const close = () => setOpen(false);

  const handle = (fn: () => void) => () => {
    close();
    fn();
  };

  return (
    <>
      <IconButton
        ref={triggerRef as never}
        iconName={Icons.MoreVert}
        variant="plain"
        aria-label={`Действия со строкой ${rowIdx + 1}`}
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
      />
      <Menu
        parent={triggerRef as never}
        isOpen={open}
        onOutsideClick={close}
        onEscape={close}
      >
        <MenuItem
          title="Добавить выше"
          iconName={Icons.AddRowUp}
          onClick={handle(onAddAbove)}
        />
        <MenuItem
          title="Добавить ниже"
          iconName={Icons.AddRowDown}
          onClick={handle(onAddBelow)}
        />
        <MenuItem
          title="Переместить вверх"
          iconName={Icons.NavArrowUp}
          disabled={isFirst}
          onClick={handle(onMoveUp)}
        />
        <MenuItem
          title="Переместить вниз"
          iconName={Icons.NavArrowDown}
          disabled={isLast}
          onClick={handle(onMoveDown)}
        />
        <MenuItem
          title="Дублировать"
          iconName={Icons.Add}
          onClick={handle(onDuplicate)}
        />
        <MenuItem
          title="Удалить"
          iconName={Icons.Delete}
          onClick={() => {
            close();
            setConfirmOpen(true);
          }}
        />
      </Menu>

      <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)}>
        <div style={{ padding: 16 }}>
          <p style={{ margin: '0 0 16px' }}>
            Удалить условие #{rowIdx + 1}?
          </p>
          <Stack direction="horizontal" gap="x2" align="center">
            <Button
              variant="outlined"
              onClick={() => setConfirmOpen(false)}
            >
              Отмена
            </Button>
            <Button
              variant="contained"
              onClick={() => {
                setConfirmOpen(false);
                onRemove();
              }}
            >
              Удалить
            </Button>
          </Stack>
        </div>
      </Dialog>
    </>
  );
}

// Stack import needed in JSX above.
export const ConditionRowActions = memo(ConditionRowActionsBase);
