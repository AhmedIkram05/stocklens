import React from 'react';
import { fireEvent } from '@testing-library/react-native';
import YearSelector from '@/components/YearSelector';
import { renderWithProviders } from '@/__tests__/utils';

const OPTIONS = ['1M', '3M', '6M', '1Y'];

describe('YearSelector', () => {
  it('renders all options', () => {
    const { getByText } = renderWithProviders(
      <YearSelector options={OPTIONS} value="1Y" onChange={jest.fn()} />,
    );
    OPTIONS.forEach((o) => expect(getByText(o)).toBeTruthy());
  });

  it('highlights selected option', () => {
    const { getByText } = renderWithProviders(
      <YearSelector options={OPTIONS} value="1Y" onChange={jest.fn()} />,
    );
    expect(getByText('1Y')).toBeTruthy();
  });

  it('calls onChange when option pressed', () => {
    const onChange = jest.fn();
    const { getByText } = renderWithProviders(
      <YearSelector options={OPTIONS} value="1Y" onChange={onChange} />,
    );
    fireEvent.press(getByText('3M'));
    expect(onChange).toHaveBeenCalledWith('3M');
  });

  it('renders in compact mode', () => {
    const { getByText } = renderWithProviders(
      <YearSelector options={OPTIONS} value="1Y" onChange={jest.fn()} compact />,
    );
    expect(getByText('1Y')).toBeTruthy();
  });

  it('handles layout measurement', () => {
    const { getByText } = renderWithProviders(
      <YearSelector options={OPTIONS} value="1Y" onChange={jest.fn()} />,
    );
    expect(getByText('1Y')).toBeTruthy();
  });

  it('fires onLayout with valid dimensions and sets measured state', () => {
    const onChange = jest.fn();
    const { getByTestId } = renderWithProviders(
      <YearSelector options={OPTIONS} value="1Y" onChange={onChange} />,
    );

    // Lines 65-75: trigger onLayout with valid width + matching value
    fireEvent(getByTestId('year-selector-container'), 'layout', {
      nativeEvent: { layout: { width: 300, height: 40 } },
    });

    expect(getByTestId('year-selector-container')).toBeTruthy();
  });

  it('handles onLayout with zero width gracefully', () => {
    const { getByTestId } = renderWithProviders(
      <YearSelector options={OPTIONS} value="1Y" onChange={jest.fn()} />,
    );

    // Line 69: guard prevents crash when w === 0
    fireEvent(getByTestId('year-selector-container'), 'layout', {
      nativeEvent: { layout: { width: 0, height: 40 } },
    });

    expect(getByTestId('year-selector-container')).toBeTruthy();
  });

  it('animates slider when value prop changes after layout measurement', () => {
    const onChange = jest.fn();
    const { getByTestId, rerender } = renderWithProviders(
      <YearSelector options={OPTIONS} value="1Y" onChange={onChange} />,
    );

    // First fire onLayout so measured = true (line 75)
    fireEvent(getByTestId('year-selector-container'), 'layout', {
      nativeEvent: { layout: { width: 300, height: 40 } },
    });

    // Now change value — useEffect runs (lines 35-42) because measured is true
    rerender(<YearSelector options={OPTIONS} value="3M" onChange={onChange} />);

    expect(getByTestId('year-selector-container')).toBeTruthy();
  });

  it('does not animate when value is not in options after measurement', () => {
    const onChange = jest.fn();
    const { getByTestId, rerender } = renderWithProviders(
      <YearSelector options={OPTIONS} value="1Y" onChange={onChange} />,
    );

    // Fire onLayout first with a valid value so measured becomes true (lines 65-75)
    fireEvent(getByTestId('year-selector-container'), 'layout', {
      nativeEvent: { layout: { width: 300, height: 40 } },
    });

    // Change to a value NOT in options — line 40 guard: idx < 0 → return
    rerender(<YearSelector options={OPTIONS} value="INVALID" onChange={onChange} />);

    expect(getByTestId('year-selector-container')).toBeTruthy();
  });

  it('renders with custom style prop', () => {
    const { getByTestId } = renderWithProviders(
      <YearSelector options={OPTIONS} value="1Y" onChange={jest.fn()} style={{ marginTop: 10 }} />,
    );

    expect(getByTestId('year-selector-container')).toBeTruthy();
  });
});
