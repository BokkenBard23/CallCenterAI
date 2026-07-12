/**
 * SimpleSelect — thin wrapper over DS Select for single-select
 * string-value dropdowns (logic operator, channel, brackets).
 *
 * DS Select is generic over the option object type and uses
 * `options: T[]` + `values: T[]` + `onChange: (values: T[]) => void`.
 * This wrapper normalises the API to a simple `{value, label}` shape
 * with a string value and single selection.
 */

import { memo, useCallback, useMemo } from 'react';
import { Select, type SelectProps } from '@beeline/design-system-react';

export interface SimpleOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface SimpleSelectProps
  extends Omit<
    SelectProps<SimpleOption>,
    'options' | 'values' | 'onChange' | 'multiple'
  > {
  options: SimpleOption[];
  value: string;
  onChange: (value: string) => void;
  /** Placeholder when no value selected. */
  placeholder?: string;
  /** Width behavior — defaults to fullWidth for table cells. */
  fullWidth?: boolean;
}

function SimpleSelectBase({
  options,
  value,
  onChange,
  placeholder,
  fullWidth = true,
  ...rest
}: SimpleSelectProps) {
  // Build the option objects with stable ids.
  const opts = useMemo(
    () => options.map((o) => ({ ...o, id: o.value })),
    [options],
  );
  const selected = useMemo(
    () => opts.filter((o) => o.value === value),
    [opts, value],
  );

  const handleChange = useCallback(
    (values: SimpleOption[]) => {
      if (values.length > 0) {
        onChange(values[0].value);
      } else {
        onChange('');
      }
    },
    [onChange],
  );

  const renderValue = useCallback(
    (values: SimpleOption[]) =>
      values.length > 0 ? values[0].label : (placeholder ?? ''),
    [placeholder],
  );

  return (
    <Select<SimpleOption>
      {...rest}
      options={opts}
      values={selected}
      onChange={handleChange}
      renderValue={renderValue}
      fullWidth={fullWidth}
      multiple={false}
    />
  );
}

export const SimpleSelect = memo(SimpleSelectBase);
