interface ErrorStateProps {
  message?: string
}

export function ErrorState({ message = 'An error occurred' }: ErrorStateProps) {
  return (
    <div className="text-center p-8 text-red-500">
      <p className="text-lg">Error</p>
      <p className="text-sm mt-2">{message}</p>
    </div>
  )
}
