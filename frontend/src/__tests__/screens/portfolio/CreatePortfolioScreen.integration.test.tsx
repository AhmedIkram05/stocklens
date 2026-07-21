import React from 'react';
import { fireEvent, waitFor } from '@testing-library/react-native';

import CreatePortfolioScreen from '@/screens/portfolio/CreatePortfolioScreen';
import { renderWithProviders } from '../../utils';
import { portfolioService } from '@/services/portfolios';
import { useNavigation } from '@react-navigation/native';

jest.mock('@/services/portfolios', () => ({
  portfolioService: {
    createPortfolio: jest.fn(),
    createCashFlow: jest.fn(),
  },
}));

jest.mock('@react-navigation/native', () => {
  const actual = jest.requireActual('@react-navigation/native');
  const actualReact = jest.requireActual('react');
  return {
    ...actual,
    useNavigation: jest.fn(),
    useRoute: jest.fn(),
    useFocusEffect: (cb: () => void) => actualReact.useEffect(cb, []),
  };
});

const mockedPortfolioService = portfolioService as jest.Mocked<typeof portfolioService>;
const mockedUseNavigation = useNavigation as jest.MockedFunction<typeof useNavigation>;

const mockCreatedPortfolio = {
  id: '1',
  name: 'Test Portfolio',
  created_at: '2024-01-01T00:00:00.000Z',
  updated_at: '2024-01-01T00:00:00.000Z',
};

describe('CreatePortfolioScreen', () => {
  let goBackSpy: jest.Mock;

  beforeEach(() => {
    jest.clearAllMocks();
    goBackSpy = jest.fn();
    mockedUseNavigation.mockReturnValue({ goBack: goBackSpy } as any);
    mockedPortfolioService.createPortfolio.mockResolvedValue(mockCreatedPortfolio);
    mockedPortfolioService.createCashFlow.mockResolvedValue({} as any);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('renders form with name, description, deposit fields', () => {
    const { getByPlaceholderText, getByText } = renderWithProviders(<CreatePortfolioScreen />, {
      providerOverrides: { withNavigation: false },
    });

    expect(getByPlaceholderText('My Portfolio')).toBeTruthy();
    expect(getByPlaceholderText("What's this portfolio for?")).toBeTruthy();
    expect(getByPlaceholderText('0.00')).toBeTruthy();
    expect(getByText('Create Portfolio')).toBeTruthy();
  });

  it('create button does not call service when name is empty', () => {
    const { getByText } = renderWithProviders(<CreatePortfolioScreen />, {
      providerOverrides: { withNavigation: false },
    });

    fireEvent.press(getByText('Create'));

    expect(mockedPortfolioService.createPortfolio).not.toHaveBeenCalled();
  });

  it('creates portfolio when name is filled and button pressed', async () => {
    const { getByPlaceholderText, getByText } = renderWithProviders(<CreatePortfolioScreen />, {
      providerOverrides: { withNavigation: false },
    });

    fireEvent.changeText(getByPlaceholderText('My Portfolio'), 'Test Portfolio');
    fireEvent.press(getByText('Create'));

    await waitFor(() => {
      expect(mockedPortfolioService.createPortfolio).toHaveBeenCalledWith({
        name: 'Test Portfolio',
        description: undefined,
      });
      expect(goBackSpy).toHaveBeenCalled();
    });
  });

  it('creates portfolio without deposit', async () => {
    const { getByPlaceholderText, getByText } = renderWithProviders(<CreatePortfolioScreen />, {
      providerOverrides: { withNavigation: false },
    });

    fireEvent.changeText(getByPlaceholderText('My Portfolio'), 'Test Portfolio');
    fireEvent.press(getByText('Create'));

    await waitFor(() => {
      expect(mockedPortfolioService.createPortfolio).toHaveBeenCalled();
      expect(mockedPortfolioService.createCashFlow).not.toHaveBeenCalled();
      expect(goBackSpy).toHaveBeenCalled();
    });
  });

  it('creates portfolio with manual deposit', async () => {
    const { getByPlaceholderText, getByText } = renderWithProviders(<CreatePortfolioScreen />, {
      providerOverrides: { withNavigation: false },
    });

    fireEvent.changeText(getByPlaceholderText('My Portfolio'), 'Test Portfolio');
    fireEvent.changeText(getByPlaceholderText('0.00'), '1000');
    fireEvent.press(getByText('Create'));

    await waitFor(() => {
      expect(mockedPortfolioService.createPortfolio).toHaveBeenCalledWith({
        name: 'Test Portfolio',
        description: undefined,
      });
      expect(mockedPortfolioService.createCashFlow).toHaveBeenCalledWith('1', {
        amount: 1000,
        source: 'manual',
        notes: 'Initial deposit',
      });
      expect(goBackSpy).toHaveBeenCalled();
    });
  });

  it('creates portfolio with receipt deposit source toggle', async () => {
    const { getByPlaceholderText, getByText } = renderWithProviders(<CreatePortfolioScreen />, {
      providerOverrides: { withNavigation: false },
    });

    fireEvent.changeText(getByPlaceholderText('My Portfolio'), 'Test Portfolio');
    fireEvent.changeText(getByPlaceholderText('0.00'), '500');
    fireEvent.press(getByText('Receipt'));
    fireEvent.press(getByText('Create'));

    await waitFor(() => {
      expect(mockedPortfolioService.createCashFlow).toHaveBeenCalledWith('1', {
        amount: 500,
        source: 'receipt',
        notes: 'Initial deposit',
      });
    });
  });

  it('shows error message on API failure', async () => {
    mockedPortfolioService.createPortfolio.mockRejectedValue(new Error('API Error'));

    const { getByPlaceholderText, getByText } = renderWithProviders(<CreatePortfolioScreen />, {
      providerOverrides: { withNavigation: false },
    });

    fireEvent.changeText(getByPlaceholderText('My Portfolio'), 'Test Portfolio');
    fireEvent.press(getByText('Create'));

    await waitFor(() => {
      expect(getByText('Failed to create portfolio. Please try again.')).toBeTruthy();
    });
  });

  it('back button calls navigation.goBack', () => {
    const { getByText } = renderWithProviders(<CreatePortfolioScreen />, {
      providerOverrides: { withNavigation: false },
    });

    fireEvent.press(getByText('Cancel'));

    expect(goBackSpy).toHaveBeenCalled();
  });

  it('inputs are disabled during loading', async () => {
    mockedPortfolioService.createPortfolio.mockImplementation(() => new Promise(() => {}));

    const { getByPlaceholderText, getByText } = renderWithProviders(<CreatePortfolioScreen />, {
      providerOverrides: { withNavigation: false },
    });

    const nameInput = getByPlaceholderText('My Portfolio');
    fireEvent.changeText(nameInput, 'Test Portfolio');

    fireEvent.press(getByText('Create'));

    await waitFor(() => {
      expect(nameInput.props.editable).toBe(false);
    });
  });
});
